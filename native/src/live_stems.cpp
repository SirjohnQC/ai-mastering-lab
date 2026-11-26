// FRANKENSTEM Live Engine v0.27.0: native, streaming stem audition.
// Experimental JUCE audio device + read-ahead playback. NO WAV renders, NO VST yet.
// All stem parameters are atomics; the audio callback never parses JSON or allocates.
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_dsp/juce_dsp.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <iostream>
#include <memory>
#include <vector>

using namespace juce;

static void reply(const var& payload) {
    // The desktop preflight and Live FX both read one JSON event per line.
    std::cout << JSON::toString(payload, true).toStdString() << std::endl;
}
static var event(const String& status, const String& message = {}) {
    auto* obj=new DynamicObject();
    obj->setProperty("status", status);
    if (message.isNotEmpty()) obj->setProperty("message", message);
    return var(obj);
}
static var prop(const var& object, const Identifier& key) {
    if (auto* d=object.getDynamicObject()) return d->getProperty(key);
    return {};
}
static float number(const var& value, float fallback) {
    if (value.isVoid()) return fallback;
    const float out=(float)(double)value;
    return std::isfinite(out) ? out : fallback;
}

class LiveMix final : public AudioSource {
public:
    struct Stem {
        String name;
        std::unique_ptr<AudioFormatReaderSource> reader;
        std::unique_ptr<BufferingAudioSource> buffered;
        AudioBuffer<float> scratch;
        int channels=0;
        std::atomic<float> drive {0.65f}, wet {0.12f}, gain {1.0f};
        std::atomic<int> style {0}; // 0 Tape, 1 Tube, 2 Soft Clip
        std::atomic<bool> enabled {false}, mute {false}, solo {false};
        float smoothedWet=0.0f;
        float smoothedGain=1.0f;
    };

    explicit LiveMix(TimeSliceThread& thread) : readAhead(thread) {}

    bool add(const File& file, AudioFormatManager& formats, String& error) {
        std::unique_ptr<AudioFormatReader> format(formats.createReaderFor(file));
        if (!format) { error="Cannot read WAV: " + file.getFullPathName(); return false; }
        if (format->numChannels<1 || format->numChannels>2) {
            error="Mono/stereo stems only: " + file.getFileName(); return false;
        }
        if (stems.size()>=32) { error="Maximum 32 live stems"; return false; }
        if (rate>0 && std::abs(rate-format->sampleRate)>1.0) {
            error="Stem sample rates differ; resample before live audition"; return false;
        }
        if (rate<=0) rate=format->sampleRate;
        if (shortestLength>0 && jmax(length,format->lengthInSamples) -
                                 jmin(shortestLength,format->lengthInSamples) >
                                 (int64)(rate*0.05)) {
            error="Stems differ in length by >50ms; align before live playback";
            return false;
        }
        shortestLength=shortestLength==0 ? format->lengthInSamples :
                       jmin(shortestLength,format->lengthInSamples);
        length=jmax(length,format->lengthInSamples);
        auto stem=std::make_unique<Stem>();
        stem->name=file.getFileName();
        stem->channels=(int)format->numChannels;
        stem->reader=std::make_unique<AudioFormatReaderSource>(format.release(), true);
        stem->buffered=std::make_unique<BufferingAudioSource>(
            stem->reader.get(),readAhead,false,65536,stem->channels,false);
        // prefillBufferOnPrepareToPlay=false: do NOT block the Windows
        // audio-device startup for every stem while waiting on disk buffers.
        // The read-ahead thread fills buffers asynchronously after prepare.
        stems.push_back(std::move(stem));
        return true;
    }

    void prepareToPlay(int maxBlock, double sampleRate) override {
        blockSize=maxBlock;
        for (auto& stem:stems) {
            stem->scratch.setSize(2,maxBlock);
            stem->scratch.clear();
            stem->buffered->prepareToPlay(maxBlock,sampleRate);
            stem->buffered->setNextReadPosition(playhead.load());
        }
        repair.reset();
    }

    void releaseResources() override {
        for (auto& stem:stems) stem->buffered->releaseResources();
    }

    void getNextAudioBlock(const AudioSourceChannelInfo& info) override {
        info.clearActiveBufferRegion();
        if (!running.load(std::memory_order_relaxed)) return;
        const bool anySolo=std::any_of(stems.begin(),stems.end(),
            [](const auto& s){return s->solo.load(std::memory_order_relaxed);});
        const int size=info.numSamples;
        const auto frame=playhead.load(std::memory_order_relaxed);
        // After a seek, hold every stem at the same frame until all disk
        // buffers have caught up. A zero timeout never waits for disk I/O.
        for (auto& stem : stems) {
            const AudioSourceChannelInfo block(&stem->scratch, 0, size);
            if (!stem->buffered->waitForNextAudioBlockReady(block, 0))
                return;
        }
        // Engine configured for stereo output; getNextAudioBlock is always <=
        // prepareToPlay block size in AudioSourcePlayer.
        for (size_t index=0; index<stems.size(); ++index) {
            auto& stem=stems[index];
            auto& scratch=stem->scratch;
            scratch.clear();
            AudioSourceChannelInfo block(&scratch,0,size);
            stem->buffered->getNextAudioBlock(block);
            const bool selected = repair.stem == static_cast<int>(index);
            const bool residual = repair.mode == Repair::residual;
            if (residual ? !selected :
                (stem->mute.load(std::memory_order_relaxed) ||
                 (anySolo && !stem->solo.load(std::memory_order_relaxed)))) continue;
            float targetWet=stem->enabled.load(std::memory_order_relaxed) ?
                stem->wet.load(std::memory_order_relaxed) : 0.0f;
            float gain=stem->gain.load(std::memory_order_relaxed);
            const float drive=stem->drive.load(std::memory_order_relaxed);
            const int style=stem->style.load(std::memory_order_relaxed);
            auto* dstL=info.buffer->getWritePointer(0,info.startSample);
            auto* dstR=info.buffer->getWritePointer(1,info.startSample);
            const float* srcL=scratch.getReadPointer(0);
            const float* srcR=stem->channels==2 ? scratch.getReadPointer(1) : srcL;
            const float tapeG=1.f+.8f*drive;
            const float tapeNorm=1.f/std::tanh(tapeG);
            const float tubeG=1.f+drive, tubeShift=.14f*drive;
            const float tubeCenter=std::tanh(tubeG*tubeShift);
            const auto shape=[=](float x)->float {
                if (style==1)
                    return (std::tanh(tubeG*(x+tubeShift))-tubeCenter)/tubeG;
                if (style==2) {
                    const float z=jlimit(-1.f,1.f,x*(1.f+.65f*drive));
                    return z-z*z*z/3.f;
                }
                return std::tanh(x*tapeG)*tapeNorm;
            };
            for (int i=0;i<size;++i) {
                // 15ms-ish smoothing on wet mix and gain reduces zipper noise.
                stem->smoothedWet+=0.002f*(targetWet-stem->smoothedWet);
                stem->smoothedGain+=0.002f*(gain-stem->smoothedGain);
                const float w=stem->smoothedWet;
                float l=srcL[i],r=srcR[i];
                // Bypass must be cheap even for a project with many stems.
                if (w>1e-6f) {
                    l=l*(1.f-w)+shape(l)*w;
                    r=r*(1.f-w)+shape(r)*w;
                }
                const float pan=stem->channels==1 ? .7071068f : 1.0f;
                if (selected) {
                    const auto position = frame + i;
                    const float edge = jlimit(0.f, 1.f, static_cast<float>(
                        jmin(position - repair.start, repair.end - position)) / repair.fade);
                    const float target = repair.mode == Repair::original ? 0.f : 1.f;
                    repair.mix += (target - repair.mix) * repair.smoothing;
                    const float removedL = (l - repair.filter(0, l)) * edge * repair.mix;
                    const float removedR = (r - repair.filter(1, r)) * edge * repair.mix;
                    l = residual ? removedL : l - removedL;
                    r = residual ? removedR : r - removedR;
                }
                dstL[i]+=l*stem->smoothedGain*pan;
                dstR[i]+=r*stem->smoothedGain*pan;
            }
        }
        // Playback monitor only. Conserve headroom before summing independent
        // stems; mastered loudness/true peak are verified on offline export.
        const float monitorGain=0.8f / std::sqrt((float)jmax(1,(int)stems.size()));
        for (int i=0;i<size;++i) {
            for (int ch=0;ch<2;++ch) {
                auto* out=info.buffer->getWritePointer(ch,info.startSample);
                out[i]=jlimit(-0.98f,0.98f,out[i]*monitorGain);
            }
        }
        playhead.fetch_add(size,std::memory_order_relaxed);
        if (playhead.load(std::memory_order_relaxed)>=length) {
            running.store(false,std::memory_order_relaxed);
        }
    }

    bool command(const var& msg, String& error) {
        const String action=prop(msg,"cmd").toString();
        if (action=="play") {
            if (playhead.load()>=length) seek(0);
            running.store(true);return true;
        }
        if (action=="pause") {running.store(false);return true;}
        if (action=="stop") {running.store(false);seek(0);return true;}
        if (action=="seek") {
            const double seconds=(double)prop(msg,"seconds");
            if (!std::isfinite(seconds) || seconds<0) {error="Invalid seek time";return false;}
            seek((int64)jlimit(0.0,(double)length,seconds*rate));
            return true;
        }
        if (action=="whistle") {
            const var stemValue = prop(msg,"stem");
            if (stemValue.isVoid()) {
                repair = {};
                return true;
            }
            const int index = static_cast<int>(stemValue);
            const double hz = static_cast<double>(prop(msg,"hz"));
            const double start = static_cast<double>(prop(msg,"start"));
            const double end = static_cast<double>(prop(msg,"end"));
            if (index < 0 || index >= static_cast<int>(stems.size()) ||
                !std::isfinite(hz) || !std::isfinite(start) || !std::isfinite(end) ||
                hz < 3500 || hz > 12000 || hz >= rate * 0.48 ||
                start < 0 || end <= start || end > static_cast<double>(length) / rate) {
                error = "Invalid whistle marker";
                return false;
            }
            repair = {};
            repair.stem = index;
            repair.start = static_cast<int64>(std::llround(start * rate));
            repair.end = static_cast<int64>(std::llround(end * rate));
            repair.fade = static_cast<float>(rate * 0.02);
            repair.smoothing = 1.f / static_cast<float>(rate * 0.005);
            auto coeff = dsp::IIR::ArrayCoefficients<float>::makePeakFilter(
                rate, static_cast<float>(hz), 55.f, Decibels::decibelsToGain(-6.f));
            repair.coefficients = {coeff[0] / coeff[3], coeff[1] / coeff[3],
                                   coeff[2] / coeff[3], coeff[4] / coeff[3],
                                   coeff[5] / coeff[3]};
            return true;
        }
        if (action=="whistle_mode") {
            const auto mode = prop(msg,"mode").toString();
            if (mode == "original" || mode == "corrected" || mode == "residual") {
                repair.mode = mode == "original" ? Repair::original :
                              mode == "corrected" ? Repair::corrected : Repair::residual;
                return true;
            }
            error = "Unknown whistle audition mode";
            return false;
        }
        if (action=="set") {
            const int i=(int)prop(msg,"stem");
            if (i<0 || i>=(int)stems.size()) {error="Invalid stem index";return false;}
            auto& s=*stems[(size_t)i];
            if (!prop(msg,"drive").isVoid())
                s.drive.store(jlimit(.1f,2.5f,number(prop(msg,"drive"),.65f)));
            if (!prop(msg,"wet").isVoid())
                s.wet.store(jlimit(0.f,.4f,number(prop(msg,"wet"),.12f)));
            if (!prop(msg,"gain_db").isVoid()) {
                const float db=jlimit(-18.f,6.f,number(prop(msg,"gain_db"),0.f));
                s.gain.store(std::pow(10.f,db/20.f));
            }
            if (!prop(msg,"style").isVoid()) {
                auto t=prop(msg,"style").toString();
                if (t!="tape" && t!="tube" && t!="softclip") {
                    error="Unknown saturation style";return false;
                }
                s.style.store(t=="tube" ? 1 : (t=="softclip" ? 2 : 0));
            }
            for (auto key : {"enabled","mute","solo"}) {
                const var flag=prop(msg,key);
                if (!flag.isVoid()) {
                    if (String(key)=="enabled") s.enabled.store((bool)flag);
                    else if (String(key)=="mute") s.mute.store((bool)flag);
                    else s.solo.store((bool)flag);
                }
            }
            return true;
        }
        if (action=="status") return true;
        error="Unknown command: "+action;
        return false;
    }

    var status() const {
        auto* obj=new DynamicObject();
        obj->setProperty("status","ok");
        obj->setProperty("playing",running.load());
        obj->setProperty("seconds",(double)playhead.load()/jmax(1.0,rate));
        obj->setProperty("duration_seconds",(double)length/jmax(1.0,rate));
        obj->setProperty("stem_count",(int)stems.size());
        return var(obj);
    }

    double sampleRate() const {return rate;}
    size_t count() const {return stems.size();}
    const Stem& stem(size_t i) const {return *stems[i];}
private:
    struct Repair {
        enum Mode { original, corrected, residual };
        Mode mode = original;
        int stem = -1;
        int64 start = 0, end = 0;
        float fade = 1.f, smoothing = 1.f, mix = 0.f;
        std::array<float, 5> coefficients {};
        std::array<std::array<float, 2>, 2> state {};

        void reset() { state = {}; }

        float filter(int channel, float input) {
            auto& delay = state[static_cast<size_t>(channel)];
            const auto& c = coefficients;
            const float output = c[0] * input + delay[0];
            delay[0] = c[1] * input - c[3] * output + delay[1];
            delay[1] = c[2] * input - c[4] * output;
            return output;
        }
    };

    void seek(int64 pos) {
        const bool wasRunning=running.exchange(false);
        for (auto& stem:stems) stem->buffered->setNextReadPosition(pos);
        playhead.store(pos);
        repair.reset();
        running.store(wasRunning);
    }
    TimeSliceThread& readAhead;
    std::vector<std::unique_ptr<Stem>> stems;
    std::atomic<bool> running {false};
    std::atomic<int64> playhead {0};
    int blockSize=512;
    double rate=0;
    int64 length=0;
    int64 shortestLength=0;
    Repair repair;
};

int main(int argc,char** argv) {
    ScopedJuceInitialiser_GUI juceInit;
    StringArray args;
    for(int i=1;i<argc;++i) args.add(String::fromUTF8(argv[i]));
    // Startup preflight can check device availability BEFORE a song is opened.
    // Never take control of a user's audio device for longer than necessary.
    if (args.size()==1 && args[0]=="--probe") {
        reply(event("progress","Checking JUCE audio device"));
        AudioDeviceManager preflight;
        const String failure=preflight.initialise(0,2,nullptr,true);
        if (failure.isNotEmpty() || preflight.getCurrentAudioDevice()==nullptr) {
            reply(event("error","JUCE audio device unavailable: "+failure));
            return 4;
        }
        auto* ok=new DynamicObject();
        ok->setProperty("status","probe_ok");
        ok->setProperty("device",preflight.getCurrentAudioDevice()->getName());
        ok->setProperty("sample_rate",preflight.getCurrentAudioDevice()->getCurrentSampleRate());
        reply(var(ok));
        preflight.closeAudioDevice();
        return 0;
    }
    if (args.size()<2 || args[0]!="--stems") {
        reply(event("error","Usage: frankenstem-live --stems first.wav second.wav ..."));
        return 2;
    }
    reply(event("progress","Opening stem files"));
    AudioFormatManager formats;
    formats.registerBasicFormats();
    TimeSliceThread thread("Frankenstem stem disk read ahead");
    thread.startThread();
    LiveMix mixer(thread);
    for (int i=1;i<args.size();++i) {
        reply(event("progress","Opening stem "+String(i)+"/"+
                    String(args.size()-1)));
        String error;
        if (!mixer.add(File(args[i]),formats,error)) {
            reply(event("error",error));
            thread.stopThread(1000);
            return 3;
        }
    }
    reply(event("progress","Opening JUCE output device"));
    AudioDeviceManager devices;
    const String failure=devices.initialise(0,2,nullptr,true);
    if (failure.isNotEmpty()) {
        reply(event("error","Audio device: "+failure));
        thread.stopThread(1000);
        return 4;
    }
    // JUCE reads stem frames natively; device rate MUST equal file rate.
    // Configure the selected device rather than changing playback pitch.
    if (auto* device=devices.getCurrentAudioDevice()) {
        if (std::abs(device->getCurrentSampleRate()-mixer.sampleRate())>1.) {
            AudioDeviceManager::AudioDeviceSetup setup;
            devices.getAudioDeviceSetup(setup);
            setup.sampleRate=mixer.sampleRate();
            const String setupError=devices.setAudioDeviceSetup(setup,true);
            if (setupError.isNotEmpty() ||
                    !devices.getCurrentAudioDevice() ||
                    std::abs(devices.getCurrentAudioDevice()->getCurrentSampleRate()-
                             mixer.sampleRate())>1.) {
                reply(event("error","Audio device cannot use stem sample rate; "
                                    "please choose a compatible Windows audio format."));
                thread.stopThread(1000);
                return 4;
            }
        }
    }
    reply(event("progress","Attaching streaming audio source"));
    std::fprintf(stderr,"[LIVE STARTUP] before player.setSource\n");
    std::fflush(stderr);
    AudioSourcePlayer player;
    player.setSource(&mixer);
    std::fprintf(stderr,"[LIVE STARTUP] after player.setSource\n");
    std::fflush(stderr);
    reply(event("progress","Starting JUCE audio callback"));
    std::fprintf(stderr,"[LIVE STARTUP] before devices.addAudioCallback\n");
    std::fflush(stderr);
    devices.addAudioCallback(&player);
    std::fprintf(stderr,"[LIVE STARTUP] after devices.addAudioCallback\n");
    std::fflush(stderr);
    {
        auto* msg=new DynamicObject();
        msg->setProperty("status","ready");
        msg->setProperty("sample_rate",mixer.sampleRate());
        msg->setProperty("whistle_preview",true);
        Array<var> stems;
        for(size_t i=0;i<mixer.count();++i) stems.add(mixer.stem(i).name);
        msg->setProperty("stems",var(stems));
        reply(var(msg));
    }
    std::string line;
    while(std::getline(std::cin,line)) {
        if (line.size()>8192) {
            reply(event("error","Command too large"));continue;
        }
        var payload=JSON::parse(String::fromUTF8(line.c_str()));
        if (!payload.isObject()) {
            reply(event("error","Invalid JSON command"));continue;
        }
        if(prop(payload,"cmd").toString()=="quit") break;
        String error;
        bool accepted;
        {
            // JUCE serializes this lock with the audio-device callback.
            const ScopedLock lock(devices.getAudioCallbackLock());
            accepted = mixer.command(payload,error);
        }
        if (!accepted) reply(event("error",error));
        else reply(mixer.status());
    }
    std::fprintf(stderr,"[LIVE STOP] disconnecting device callback\n");
    std::fflush(stderr);
    devices.removeAudioCallback(&player);
    player.setSource(nullptr);
    // player.setSource(nullptr) releases prepared stream resources.
    // Keep the read-ahead worker alive until the player has detached.
    thread.stopThread(2000);
    return 0;
}
