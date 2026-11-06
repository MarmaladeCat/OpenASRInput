cmake_minimum_required(VERSION 3.20)
project(
  OpenASRInputFcitx
  VERSION 1.0.1
  LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(OPENASRINPUT_SDK_ROOT
    ""
    CACHE PATH "Extracted SDK prefix (directory containing usr)")

if(OPENASRINPUT_SDK_ROOT)
  # Extracted Debian SDKs refer to runtime .so files absent from the archive. Use their public
  # headers with the already-installed, matching runtime libs.
  add_library(fcitx_sdk INTERFACE)
  target_include_directories(
    fcitx_sdk
    INTERFACE "${OPENASRINPUT_SDK_ROOT}/usr/include/Fcitx5/Core"
              "${OPENASRINPUT_SDK_ROOT}/usr/include/Fcitx5/Utils"
              "${OPENASRINPUT_SDK_ROOT}/usr/include/Fcitx5/Config")
  find_library(FCITX_CORE NAMES libFcitx5Core.so.7 REQUIRED)
  find_library(FCITX_UTILS NAMES libFcitx5Utils.so.2 REQUIRED)
  find_library(FCITX_CONFIG NAMES libFcitx5Config.so.6 REQUIRED)
  target_link_libraries(fcitx_sdk INTERFACE ${FCITX_CORE} ${FCITX_UTILS} ${FCITX_CONFIG})
else()
  find_package(Fcitx5Core 5.0.14 REQUIRED)
  add_library(fcitx_sdk INTERFACE)
  target_link_libraries(fcitx_sdk INTERFACE Fcitx5::Core)
endif()

find_package(X11 REQUIRED COMPONENTS Xext)
add_library(voice_gui INTERFACE)
target_link_libraries(voice_gui INTERFACE X11::X11 X11::Xext ${CMAKE_DL_LIBS})
if(OPENASRINPUT_SDK_ROOT)
  target_include_directories(
    voice_gui
    INTERFACE "${OPENASRINPUT_SDK_ROOT}/usr/include"
              "${OPENASRINPUT_SDK_ROOT}/usr/include/cairo"
              "${OPENASRINPUT_SDK_ROOT}/usr/include/pango-1.0"
              "${OPENASRINPUT_SDK_ROOT}/usr/include/harfbuzz"
              "${OPENASRINPUT_SDK_ROOT}/usr/include/glib-2.0"
              "${OPENASRINPUT_SDK_ROOT}/usr/lib/${CMAKE_LIBRARY_ARCHITECTURE}/glib-2.0/include")
  find_library(VOICE_CAIRO NAMES libcairo.so.2 REQUIRED)
  find_library(VOICE_PANGO NAMES libpango-1.0.so.0 REQUIRED)
  find_library(VOICE_PANGOCAIRO NAMES libpangocairo-1.0.so.0 REQUIRED)
  find_library(VOICE_GOBJECT NAMES libgobject-2.0.so.0 REQUIRED)
  find_library(VOICE_GLIB NAMES libglib-2.0.so.0 REQUIRED)
  find_library(VOICE_ICU NAMES libicui18n.so.78 REQUIRED)
  find_library(VOICE_ICUUC NAMES libicuuc.so.78 REQUIRED)
  target_link_libraries(
    voice_gui
    INTERFACE ${VOICE_CAIRO}
              ${VOICE_PANGO}
              ${VOICE_PANGOCAIRO}
              ${VOICE_GOBJECT}
              ${VOICE_GLIB}
              ${VOICE_ICU}
              ${VOICE_ICUUC})
else()
  find_package(PkgConfig REQUIRED)
  pkg_check_modules(VOICE_PANGO REQUIRED IMPORTED_TARGET pangocairo)
  find_package(ICU REQUIRED COMPONENTS uc i18n)
  target_link_libraries(voice_gui INTERFACE PkgConfig::VOICE_PANGO ICU::uc ICU::i18n)
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(WAYLAND REQUIRED IMPORTED_TARGET wayland-client)
add_library(
  panel_host STATIC ../common/preview_buffer.cpp ../panel/voice_panel.cpp ../panel/gnome_panel.cpp
                    ../panel/wayland_panel.cpp ../panel/layer_shell_protocol.cpp)
target_include_directories(panel_host PUBLIC ../common ../panel)
if(OPENASRINPUT_SDK_ROOT)
  target_include_directories(panel_host PUBLIC "${OPENASRINPUT_SDK_ROOT}/usr/include/Fcitx5/Utils")
  target_link_libraries(panel_host PUBLIC ${FCITX_UTILS})
else()
  target_link_libraries(panel_host PUBLIC Fcitx5::Utils)
endif()
target_link_libraries(panel_host PRIVATE voice_gui PkgConfig::WAYLAND)
target_compile_options(panel_host PRIVATE -Wall -Wextra -Werror)
add_executable(voice-panel ../panel/standalone.cpp)
target_link_libraries(voice-panel PRIVATE panel_host voice_gui)
target_compile_options(voice-panel PRIVATE -Wall -Wextra -Werror)
add_library(cursor_bridge STATIC cursor_bridge.cpp)
target_include_directories(cursor_bridge PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/../common")
target_link_libraries(cursor_bridge PUBLIC fcitx_sdk panel_host)
target_link_libraries(cursor_bridge PRIVATE voice_gui PkgConfig::WAYLAND)
target_compile_options(cursor_bridge PRIVATE -Wall -Wextra -Werror)
add_library(openasrinput MODULE addon.cpp socket_server.cpp chord_guard.cpp)
target_link_libraries(openasrinput PRIVATE cursor_bridge)
target_compile_options(openasrinput PRIVATE -Wall -Wextra -Werror)
set_target_properties(openasrinput PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
configure_file(openasrinput.conf "${CMAKE_BINARY_DIR}/share/fcitx5/addon/openasrinput.conf"
               COPYONLY)

enable_testing()
set(TEST_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/../../../tests/native")
add_executable(native_check "${TEST_SOURCES}/native_check.cpp" chord_guard.cpp)
target_include_directories(native_check PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(native_check PRIVATE cursor_bridge)
target_compile_options(native_check PRIVATE -Wall -Wextra -Werror)
add_executable(native_host "${TEST_SOURCES}/native_host.cpp" socket_server.cpp)
target_include_directories(native_host PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(native_host PRIVATE fcitx_sdk)
target_compile_options(native_host PRIVATE -Wall -Wextra -Werror)
add_executable(preview_check "${TEST_SOURCES}/preview_check.cpp" ../common/preview_buffer.cpp)
target_include_directories(preview_check PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../common")
target_link_libraries(preview_check PRIVATE voice_gui)
target_compile_options(preview_check PRIVATE -Wall -Wextra -Werror)
add_test(NAME preview_buffer COMMAND preview_check)
add_executable(geometry_check "${TEST_SOURCES}/geometry_check.cpp")
target_include_directories(geometry_check PRIVATE ../common)
add_test(NAME monitor_geometry COMMAND geometry_check)
add_executable(panel_live_check "${TEST_SOURCES}/panel_live_check.cpp")
target_link_libraries(panel_live_check PRIVATE panel_host voice_gui)
find_program(XVFB_RUN xvfb-run)
if(XVFB_RUN)
  add_test(NAME panel_hot_update COMMAND ${XVFB_RUN} -a $<TARGET_FILE:panel_live_check>)
endif()
pkg_check_modules(WAYLAND_SERVER IMPORTED_TARGET wayland-server)
if(WAYLAND_SERVER_FOUND)
  find_package(Threads REQUIRED)
  add_executable(wayland_check "${TEST_SOURCES}/wayland_check.cpp")
  target_include_directories(wayland_check PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
  target_link_libraries(wayland_check PRIVATE cursor_bridge voice_gui PkgConfig::WAYLAND_SERVER
                                              Threads::Threads)
  target_compile_options(wayland_check PRIVATE -Wall -Wextra -Werror)
  add_test(NAME wayland_panel COMMAND wayland_check)
endif()
# Run via scripts/test_native.py: it sets a separate HOME/XDG profile first.
