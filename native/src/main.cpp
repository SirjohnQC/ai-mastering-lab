#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_utils/juce_audio_utils.h>
#include <iostream>
#include <memory>
#include <vector>
#include <cmath>
#include <cstdio>
#include "live_plugin_audition.h"

using namespace juce;

static void checkpoint(const char* msg) { std::fprintf(stderr, "[HOST DEBUG] %s\n", msg); std::fflush(stderr); }

static void printJson(const var& v) { std::cout << JSON::toString(v, true).toStdString() << std::endl; }
static var error(const String& s) { auto* o = new DynamicObject(); o->setProperty("error", s); return var(o); }
static String arg(const StringArray& a, const String& key, const String& fallback = {}) {
    int i = a.indexOf(key); return (i >= 0 && i + 1 < a.size()) ? a[i+1] : fallback;
}
static StringArray repeatedArgs(const StringArray& a, const String& key) {
    StringArray values;
    for (int i = 0; i + 1 < a.size(); ++i)
        if (a[i] == key) values.add(a[i + 1]);
    return values;
}
static std::unique_ptr<AudioPluginInstance> loadPlugin(const String& path, double sampleRate, int blockSize, String& failure) {
    AudioPluginFormatManager manager;
    manager.addDefaultFormats();
    KnownPluginList known;
    OwnedArray<PluginDescription> descriptions;
    for (auto* format : manager.getFormats()) {
        if (format->getName() == "VST3") {
            known.scanAndAddFile(path, true, descriptions, *format);
        }
    }
    if (descriptions.isEmpty()) { failure = "No VST3 plugin description found. Verify --plugin path and architecture."; return {}; }
    auto instance = manager.createPluginInstance(*descriptions[0], sampleRate, blockSize, failure);
    return instance;
}
static var describe(AudioPluginInstance& plugin) {
    auto* root = new DynamicObject();
    root->setProperty("name", plugin.getName());
    root->setProperty("latency_samples", plugin.getLatencySamples());
    Array<var> params;
    auto& all = plugin.getParameters();
    for (int i = 0; i < all.size(); ++i) {
        auto* p = all[i];
        auto* obj = new DynamicObject();
        obj->setProperty("index", i);
        obj->setProperty("name", p->getName(256));
        obj->setProperty("value", p->getValue());
        obj->setProperty("text", p->getCurrentValueAsText());
        obj->setProperty("automatable", p->isAutomatable());
        if (auto* withId = dynamic_cast<AudioProcessorParameterWithID*>(p))
            obj->setProperty("parameter_id", withId->paramID);
        params.add(var(obj));
    }
    root->setProperty("parameters", var(params));
    return var(root);
}
int main(int argc, char** argv) {
    ScopedJuceInitialiser_GUI init;
    StringArray a;
    for (int i = 1; i < argc; ++i) a.add(String::fromUTF8(argv[i]));
    if (a.isEmpty() || a[0] == "--help") {
        std::cout << "Usage:\n  mastering-host inspect --plugin PATH [--sample-rate 48000]\n  mastering-host render --plugin PATH --input INPUT.wav --output OUTPUT.wav [--set INDEX:VALUE ...] [--state-in FILE] [--state-out FILE]\n  mastering-host audition --plugin PATH --input INPUT.wav [--set INDEX:VALUE ...]\n";
        return 0;
    }
    const String cmd = a[0], path = arg(a, "--plugin");
    checkpoint("parsed arguments");
    if (path.isEmpty()) { printJson(error("Missing --plugin")); return 2; }
    const int blockSize = 512;
    const File input(arg(a, "--input"));
    AudioFormatManager formats; formats.registerBasicFormats();
    std::unique_ptr<AudioFormatReader> reader;
    double sampleRate = arg(a, "--sample-rate", "48000").getDoubleValue();
    if (cmd == "render" || cmd == "audition") {
        reader.reset(formats.createReaderFor(input));
        if (!reader) { printJson(error("Cannot read input WAV")); return 3; }
        sampleRate = reader->sampleRate;
        if (reader->numChannels != 2) { printJson(error("Initial prototype accepts stereo WAV only")); return 3; }
    }
    String failure;
    checkpoint("before loadPlugin");
    auto plugin = loadPlugin(path, sampleRate, blockSize, failure);
    checkpoint("after loadPlugin");
    if (!plugin) { printJson(error(failure)); return 4; }
    std::fprintf(stderr, "[HOST DEBUG] channels before layout: in=%d out=%d buses in=%d out=%d\n", plugin->getTotalNumInputChannels(), plugin->getTotalNumOutputChannels(), plugin->getBusCount(true), plugin->getBusCount(false)); std::fflush(stderr);
    // Preserve the plugin's default multi-bus layout. For example, Pro-Q 4 can
    // expose stereo main input + stereo sidechain (4 total input channels).
    // JUCE processBlock requires space for the declared channel layout; do not
    // force a one-input-bus layout that the plugin rejects.
    const auto mainInput = plugin->getChannelLayoutOfBus(true, 0);
    const auto mainOutput = plugin->getChannelLayoutOfBus(false, 0);
    if (mainInput != AudioChannelSet::stereo() || mainOutput != AudioChannelSet::stereo()) {
        printJson(error("Current plugin main input/output must be stereo for this prototype"));
        return 7;
    }
    const int inputChannels = plugin->getTotalNumInputChannels();
    const int outputChannels = plugin->getTotalNumOutputChannels();
    const int processingChannels = jmax(inputChannels, outputChannels);
    std::fprintf(stderr, "[HOST DEBUG] preserving bus layout: input=%d output=%d processing=%d\n",
                 inputChannels, outputChannels, processingChannels);
    std::fflush(stderr);
    if ((cmd == "render" || cmd == "audition") && (inputChannels < 2 || outputChannels < 2 || processingChannels > 64)) {
        printJson(error("Unsupported plugin channel configuration"));
        return 7;
    }
    plugin->setProcessingPrecision(AudioProcessor::singlePrecision);
    plugin->setRateAndBufferSizeDetails(sampleRate, blockSize);
    checkpoint("before prepareToPlay");
    plugin->prepareToPlay(sampleRate, blockSize);
    checkpoint("after prepareToPlay");
    // PRO_C3_TEXT_PROBE_V1: READ ONLY, no setValue(), no processBlock(), no WAV.
    if (cmd == "probe") {
        auto* obj = new DynamicObject();
        obj->setProperty("name", plugin->getName());
        obj->setProperty("read_only", true);
        obj->setProperty("method", "getText");
        Array<var> readings;
        auto& params = plugin->getParameters();
        const int ids[] = {1, 4, 7, 8};
        const double grid[] = {0.05, 0.15, 0.30, 0.50, 0.70, 0.85, 0.95};
        for (int idx : ids) {
            if (idx < 0 || idx >= params.size()) {
                printJson(error("Pro-C 3 parameter index missing"));
                plugin->releaseResources(); return 5;
            }
            auto* param = params[idx];
            for (double value : grid) {
                auto* pt = new DynamicObject();
                pt->setProperty("index", idx);
                pt->setProperty("name", param->getName(256));
                pt->setProperty("normalized", value);
                pt->setProperty("display_text", param->getText((float)value, 100));
                readings.add(var(pt));
            }
        }
        obj->setProperty("probe_points", var(readings));
        printJson(var(obj));
        plugin->releaseResources(); return 0;
    }
    if (cmd == "inspect") { printJson(describe(*plugin)); plugin->releaseResources(); return 0; }
    if (cmd != "render") { printJson(error("Unknown command")); return 2; }
    const String stateIn = arg(a, "--state-in");
    if (stateIn.isNotEmpty()) {
        MemoryBlock data;
        if (!File(stateIn).loadFileAsData(data)) { printJson(error("Cannot load state file")); return 5; }
        plugin->setStateInformation(data.getData(), (int)data.getSize());
    }
    // Apply validated parameter changes; repeated --set INDEX:NORMALIZED_VALUE.
    // Pro-Q 4 band 1 example: --set 0:1 --set 3:0.6 (used + positive gain).
    Array<var> changes;
    const auto changesText = repeatedArgs(a, "--set");
    // Preserve compatibility with the original single-parameter command.
    StringArray allChanges(changesText);
    const String legacyIndex = arg(a, "--parameter-index");
    if (legacyIndex.isNotEmpty())
        allChanges.add(legacyIndex + ":" + arg(a, "--value", "0.5"));
    auto& params = plugin->getParameters();
    // Validate all commands before changing any plugin state.
    for (const auto& change : allChanges) {
        const int colon = change.indexOfChar(':');
        if (colon <= 0 || colon == change.length() - 1) {
            printJson(error("Invalid --set format. Use INDEX:VALUE, e.g. --set 0:1")); return 5;
        }
        const String indexText = change.substring(0, colon).trim();
        const String valueText = change.substring(colon + 1).trim();
        if (!indexText.containsOnly("0123456789") ||
            !valueText.containsOnly("0123456789.+-eE")) {
            printJson(error("Invalid --set index or value")); return 5;
        }
        const int idx = indexText.getIntValue();
        const float value = valueText.getFloatValue();
        if (idx < 0 || idx >= params.size() || !std::isfinite(value) || value < 0.f || value > 1.f) {
            printJson(error("Parameter index out of range or value not within 0..1")); return 5;
        }
        if (!params[idx]->isAutomatable()) {
            printJson(error("Parameter is not automatable: " + params[idx]->getName(128))); return 5;
        }
    }
    for (const auto& change : allChanges) {
        const int colon = change.indexOfChar(':');
        const int idx = change.substring(0, colon).getIntValue();
        const float value = change.substring(colon + 1).getFloatValue();
        params[idx]->setValueNotifyingHost(value);
        auto* item = new DynamicObject();
        item->setProperty("index", idx);
        item->setProperty("name", params[idx]->getName(128));
        item->setProperty("requested", value);
        item->setProperty("actual", params[idx]->getValue());
        item->setProperty("text", params[idx]->getCurrentValueAsText());
        changes.add(var(item));
    }
    checkpoint("parameters applied");
    const String stateOut = arg(a, "--state-out");
    if (stateOut.isNotEmpty()) {
        MemoryBlock data; plugin->getStateInformation(data);
        if (!File(stateOut).replaceWithData(data.getData(), data.getSize())) { printJson(error("Cannot save state file")); return 5; }
    }
    checkpoint("state handling complete");
    if (cmd == "audition") {
        if (processingChannels > 16) { printJson(error("Unsupported audition channel count")); return 7; }
        const auto failure = auditionPlugin(*reader, *plugin, processingChannels);
        plugin->releaseResources();
        if (failure.isNotEmpty()) { printJson(error(failure)); return 6; }
        return 0;
    }
    const String outputPath = arg(a, "--output");
    const File output(outputPath);
    if (outputPath.isEmpty() || output == input) { printJson(error("Output must differ from input")); return 5; }
    if (output.getParentDirectory().createDirectory().failed()) { printJson(error("Cannot create output directory")); return 5; }
    checkpoint("before output stream");
    auto stream = output.createOutputStream();
    if (!stream) { printJson(error("Cannot open output WAV")); return 5; }
    WavAudioFormat wav;
    auto writer = std::unique_ptr<AudioFormatWriter>(wav.createWriterFor(stream.get(), sampleRate, 2, 24, {}, 0));
    if (!writer) { printJson(error("Cannot create WAV writer")); return 5; }
    stream.release(); // writer owns stream
    checkpoint("WAV writer created");
    AudioBuffer<float> buffer(processingChannels, blockSize);
    AudioBuffer<float> inputBuffer(2, blockSize);
    MidiBuffer midi;
    const int64 length = reader->lengthInSamples;
    const int latency = jmax(0, plugin->getLatencySamples());
    // Flush latency and a bounded reverb tail, then trim the leading delay.
    const int tail = jlimit(0, (int)(sampleRate * 10), (int)std::ceil(plugin->getTailLengthSeconds() * sampleRate));
    std::fprintf(stderr, "[HOST DEBUG] length=%lld latency=%d tail=%d\n", (long long)length, latency, tail); std::fflush(stderr);
    const int64 total = length + latency + tail;
    const int64 desired = length + tail;
    int64 written = 0;
    for (int64 pos = 0; pos < total; pos += blockSize) {
        const int n = (int)jmin((int64)blockSize, total - pos);
        buffer.clear(); // All auxiliary buses (e.g. sidechain) remain silent.
        inputBuffer.clear();
        if (pos < length) {
            const int count = (int)jmin((int64)n, length - pos);
            if (!reader->read(&inputBuffer, 0, count, pos, true, true)) {
                printJson(error("WAV input read failed")); return 6;
            }
            for (int ch = 0; ch < 2; ++ch)
                buffer.copyFrom(ch, 0, inputBuffer, ch, 0, count);
        }
        midi.clear();
        if (pos == 0) checkpoint("before FIRST processBlock");
        plugin->processBlock(buffer, midi);
        if (pos == 0) checkpoint("after FIRST processBlock");
        const int skip = (int)jlimit((int64)0, (int64)n, (int64)latency - pos);
        const int toWrite = (int)jmin((int64)(n - skip), desired - written);
        if (toWrite > 0) {
            AudioBuffer<float> outChunk(2, toWrite);
            for (int ch = 0; ch < 2; ++ch) outChunk.copyFrom(ch, 0, buffer, ch, skip, toWrite);
            if (pos == 0) checkpoint("before FIRST write");
            if (!writer->writeFromAudioSampleBuffer(outChunk, 0, toWrite)) { printJson(error("WAV write failed")); return 6; }
            written += toWrite;
            if (pos == 0) checkpoint("after FIRST write");
        }
    }
    checkpoint("before writer close");
    writer.reset();
    checkpoint("after writer close");
    checkpoint("before plugin releaseResources");
    plugin->releaseResources();
    checkpoint("after plugin releaseResources");
    auto* result = new DynamicObject();
    result->setProperty("status", "ok");
    result->setProperty("parameter_changes", var(changes));
    result->setProperty("output", output.getFullPathName());
    result->setProperty("sample_rate", sampleRate);
    result->setProperty("latency_samples", latency);
    result->setProperty("tail_samples", tail);
    result->setProperty("written_samples", (double)written);
    printJson(var(result));
    return 0;
}
