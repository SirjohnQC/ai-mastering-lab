// FRANKENSTEM Live Engine v0.27.0: native, streaming stem audition.
// Experimental JUCE audio device + read-ahead playback. NO WAV renders, NO VST yet.
// All stem parameters are atomics; the audio callback never parses JSON or allocates.
#include <juce_audio_utils/juce_audio_utils.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_dsp/juce_dsp.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <iostream>
#include <memory>
#include <vector>

using namespace juce;

static void reply(const var& payload) {
    std::cout << JSON::toString(payload, false).toStdString() << std::endl;
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
            stem->reader.get(),readAhead,false,65536,stem->channels,true);
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
        // Engine configured for stereo output; getNextAudioBlock is always <=
        // prepareToPlay block size in AudioSourcePlayer.
        for (auto& stem:stems) {
            auto& scratch=stem->scratch;
            scratch.clear();
            AudioSourceChannelInfo block(&scratch,0,size);
            stem->buffered->getNextAudioBlock(block);
            if (stem->mute.load(std::memory_order_relaxed) ||
                (anySolo && !stem->solo.load(std::memory_order_relaxed))) continue;
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
    void seek(int64 pos) {
        const bool wasRunning=running.exchange(false);
        for (auto& stem:stems) stem->buffered->setNextReadPosition(pos);
        playhead.store(pos);
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
};

int main(int argc,char** argv) {
    ScopedJuceInitialiser_GUI juceInit;
    StringArray args;
    for(int i=1;i<argc;++i) args.add(String::fromUTF8(argv[i]));
    if (args.size()<2 || args[0]!="--stems") {
        reply(event("error","Usage: frankenstem-live --stems first.wav second.wav ..."));
        return 2;
    }
    AudioFormatManager formats;
    formats.registerBasicFormats();
    TimeSliceThread thread("Frankenstem stem disk read ahead");
    thread.startThread();
    LiveMix mixer(thread);
    for (int i=1;i<args.size();++i) {
        String error;
        if (!mixer.add(File(args[i]),formats,error)) {
            reply(event("error",error));
            thread.stopThread(1000);
            return 3;
        }
    }
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
    AudioSourcePlayer player;
    player.setSource(&mixer);
    devices.addAudioCallback(&player);
    {
        auto* msg=new DynamicObject();
        msg->setProperty("status","ready");
        msg->setProperty("sample_rate",mixer.sampleRate());
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
        if (!mixer.command(payload,error)) reply(event("error",error));
        else reply(mixer.status());
    }
    devices.removeAudioCallback(&player);
    player.setSource(nullptr);
    thread.stopThread(2000);
    return 0;
}
