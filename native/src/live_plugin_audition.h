#pragma once

#include <juce_audio_utils/juce_audio_utils.h>
#include <atomic>
#include <cmath>
#include <iostream>

namespace {

class PluginAuditionSource final : public juce::AudioSource {
public:
    PluginAuditionSource(juce::BufferingAudioSource& input,
                         juce::AudioPluginInstance& plugin, int channels, double rate)
        : input(input), plugin(plugin), channels(channels), rate(rate) {}

    void prepareToPlay(int maxBlock, double sampleRate) override {
        validDevice = std::abs(sampleRate - rate) < 0.5;
        audio.setSize(channels, maxBlock);
        midi.ensureSize(4096);
        if (validDevice) {
            input.prepareToPlay(maxBlock, sampleRate);
            plugin.releaseResources();
            plugin.setProcessingPrecision(juce::AudioProcessor::singlePrecision);
            plugin.prepareToPlay(sampleRate, maxBlock);
            validDevice = plugin.getLatencySamples() == 0;
        }
    }

    void releaseResources() override { input.releaseResources(); }

    void getNextAudioBlock(const juce::AudioSourceChannelInfo& output) override {
        juce::ScopedNoDenormals noDenormals;
        output.clearActiveBufferRegion();
        const int count = output.numSamples;
        if (!validDevice || output.buffer->getNumChannels() < 2
            || count > audio.getNumSamples())
            return;

        audio.clear();
        juce::AudioSourceChannelInfo block(&audio, 0, count);
        if (!input.waitForNextAudioBlockReady(block, 0))
            return;
        const int remaining = static_cast<int>(juce::jlimit(
            static_cast<juce::int64>(0), static_cast<juce::int64>(count),
            input.getTotalLength() - input.getNextReadPosition()));
        if (remaining == 0)
            return;
        input.getNextAudioBlock(block);
        for (int ch = 0; ch < 2; ++ch)
            output.buffer->copyFrom(ch, output.startSample, audio, ch, 0, remaining);

        juce::AudioBuffer<float> wet(audio.getArrayOfWritePointers(), channels, count);
        midi.clear();
        plugin.processBlock(wet, midi);
        const float target = enabled.load(std::memory_order_relaxed) ? 1.0f : 0.0f;
        const float smoothing = static_cast<float>(1.0 / (0.01 * rate));
        for (int i = 0; i < remaining; ++i) {
            blend += (target - blend) * smoothing;
            for (int ch = 0; ch < 2; ++ch) {
                auto* dry = output.buffer->getWritePointer(ch, output.startSample);
                const float processed = wet.getSample(ch, i);
                const float sample = std::isfinite(processed)
                    ? dry[i] + blend * (processed - dry[i]) : dry[i];
                dry[i] = juce::jlimit(-0.98f, 0.98f, sample * 0.8f);
            }
        }
    }

    std::atomic<bool> enabled { false };
    bool validDevice = false;

private:
    juce::BufferingAudioSource& input;
    juce::AudioPluginInstance& plugin;
    int channels;
    double rate;
    float blend = 0.0f;
    juce::AudioBuffer<float> audio;
    juce::MidiBuffer midi;
};

juce::String auditionPlugin(juce::AudioFormatReader& reader,
                           juce::AudioPluginInstance& plugin, int channels) {
    using namespace juce;
    AudioDeviceManager device;
    const auto error = device.initialise(0, 2, nullptr, true);
    if (error.isNotEmpty())
        return error;
    AudioDeviceManager::AudioDeviceSetup setup;
    device.getAudioDeviceSetup(setup);
    if (std::abs(setup.sampleRate - reader.sampleRate) >= 0.5) {
        setup.sampleRate = reader.sampleRate;
        const auto setupError = device.setAudioDeviceSetup(setup, true);
        if (setupError.isNotEmpty())
            return setupError;
    }
    auto* activeDevice = device.getCurrentAudioDevice();
    if (!activeDevice || activeDevice->getActiveOutputChannels().countNumberOfSetBits() < 2)
        return "A stereo output device is required.";

    TimeSliceThread disk("Plugin audition read ahead");
    disk.startThread();
    AudioFormatReaderSource file(&reader, false);
    BufferingAudioSource buffered(&file, disk, false, 65536, 2, false);
    PluginAuditionSource source(buffered, plugin, channels, reader.sampleRate);
    AudioSourcePlayer player;
    player.setSource(&source);
    device.addAudioCallback(&player);
    bool ready;
    {
        const ScopedLock lock(device.getAudioCallbackLock());
        ready = source.validDevice;
    }

    if (ready) {
        std::cerr << "Playing dry. Enter wet, dry, or quit." << std::endl;
        std::string command;
        while (std::getline(std::cin, command) && command != "quit") {
            if (command == "wet" || command == "dry")
                source.enabled.store(command == "wet", std::memory_order_relaxed);
        }
    }
    device.removeAudioCallback(&player);
    player.setSource(nullptr);
    disk.stopThread(2000);
    return ready ? String() : String("Audition requires matching sample rates and zero plugin latency.");
}
}
