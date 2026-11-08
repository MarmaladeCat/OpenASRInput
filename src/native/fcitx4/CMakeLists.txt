cmake_minimum_required(VERSION 3.16)
project(
  OpenASRInputFcitx4
  VERSION 1.0.2
  LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(PkgConfig REQUIRED)
pkg_check_modules(FCITX4 REQUIRED IMPORTED_TARGET "fcitx>=4.2.9.8")
pkg_check_modules(PANGO REQUIRED IMPORTED_TARGET pangocairo)
find_package(X11 REQUIRED)
find_package(ICU REQUIRED COMPONENTS uc i18n)
add_library(openasrinput4 MODULE addon.cpp panel.cpp ../common/preview_buffer.cpp)
target_include_directories(openasrinput4 PRIVATE ../common ${X11_INCLUDE_DIR})
target_link_libraries(
  openasrinput4
  PRIVATE PkgConfig::FCITX4
          PkgConfig::PANGO
          ${X11_LIBRARIES}
          ${X11_Xext_LIB}
          ICU::uc
          ICU::i18n
          ${CMAKE_DL_LIBS})
target_compile_options(openasrinput4 PRIVATE -Wall -Wextra -Werror)
set_target_properties(
  openasrinput4
  PROPERTIES PREFIX ""
             OUTPUT_NAME "fcitx-openasrinput"
             LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")
configure_file(fcitx-openasrinput.conf
               "${CMAKE_BINARY_DIR}/share/fcitx/addon/fcitx-openasrinput.conf" COPYONLY)
add_executable(fcitx4_xim_probe ../../../tests/native/fcitx4_xim_probe.cpp)
target_link_libraries(fcitx4_xim_probe PRIVATE ${X11_LIBRARIES})
enable_testing()
add_executable(preview_check ../../../tests/native/preview_check.cpp ../common/preview_buffer.cpp)
target_include_directories(preview_check PRIVATE ../common)
target_link_libraries(preview_check PRIVATE ICU::uc ICU::i18n)
add_test(NAME preview_buffer COMMAND preview_check)
add_executable(geometry_check ../../../tests/native/geometry_check.cpp)
target_include_directories(geometry_check PRIVATE ../common)
add_test(NAME monitor_geometry COMMAND geometry_check)
add_executable(panel_live_check ../../../tests/native/panel_live_check.cpp panel.cpp
                                ../common/preview_buffer.cpp)
target_compile_definitions(panel_live_check PRIVATE FCITX4_PANEL)
target_include_directories(panel_live_check PRIVATE . ../common)
target_link_libraries(panel_live_check PRIVATE PkgConfig::PANGO ${X11_LIBRARIES} ${X11_Xext_LIB}
                                               ICU::uc ICU::i18n ${CMAKE_DL_LIBS})
find_program(XVFB_RUN xvfb-run)
if(XVFB_RUN)
  add_test(NAME panel_hot_update COMMAND ${XVFB_RUN} -a $<TARGET_FILE:panel_live_check>)
endif()
