cmake_minimum_required(VERSION 3.22)
project(AIMasteringHost VERSION 0.2.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include(FetchContent)
FetchContent_Declare(JUCE GIT_REPOSITORY https://github.com/juce-framework/JUCE.git GIT_TAG 8.0.10 GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(JUCE)
juce_add_console_app(mastering-host PRODUCT_NAME "AI Mastering Host")
target_sources(mastering-host PRIVATE src/main.cpp)
target_compile_definitions(mastering-host PRIVATE JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_PLUGINHOST_VST3=1 JUCE_PLUGINHOST_AU=0)
target_link_libraries(mastering-host PRIVATE juce::juce_audio_utils juce::juce_audio_processors juce::juce_audio_formats juce::juce_dsp juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)

# Dedicated real-time player. Keep the existing mastering-host offline
# render path unchanged until this live MVP is validated on Windows.
juce_add_console_app(frankenstem-live PRODUCT_NAME "FRANKENSTEM Live Engine")
target_sources(frankenstem-live PRIVATE src/live_stems.cpp)
target_compile_definitions(frankenstem-live PRIVATE JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_link_libraries(frankenstem-live PRIVATE
    juce::juce_audio_utils juce::juce_audio_devices juce::juce_audio_formats
    juce::juce_dsp juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags)
