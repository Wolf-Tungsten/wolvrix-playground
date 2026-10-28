cmake_minimum_required(VERSION 3.26)
project(grhsim32 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
set(WOLVRIX_ENABLE_MT_KAHYPAR OFF CACHE BOOL "Replay labels from the independent six-axis solver" FORCE)
add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../../wolvrix" wolvrix EXCLUDE_FROM_ALL)
set(REPO "${CMAKE_CURRENT_SOURCE_DIR}/../..")
foreach(pair IN ITEMS "frontend;frontend.cpp" "initial_graph;fine_state_probe.cpp"
        "partition;../../scripts/repcut_grhsim_partition.cpp"
        "replay;../../scripts/repcut_grhsim_replay.cpp"
        "context;../../scripts/repcut_grhsim_context_probe.cpp"
        "assignment_eval;../../scripts/repcut_grhsim_assignment_eval.cpp")
    list(GET pair 0 name)
    list(GET pair 1 source)
    add_executable(grhsim32_${name} "${source}")
    target_link_libraries(grhsim32_${name} PRIVATE wolvrix::lib)
    target_include_directories(grhsim32_${name} PRIVATE "${REPO}/scripts")
    target_compile_options(grhsim32_${name} PRIVATE -Wno-subobject-linkage)
endforeach()
add_executable(grhsim32_score score.cpp)
add_library(grhsim32_codepage SHARED codepage.cpp)
target_link_libraries(grhsim32_codepage PRIVATE ${CMAKE_DL_LIBS})
add_library(grhsim32_collapse_retry SHARED "${REPO}/scripts/xiangshan_codepage_retry.cpp")
add_custom_target(grhsim32_tools DEPENDS grhsim32_frontend grhsim32_initial_graph
    grhsim32_partition grhsim32_replay grhsim32_context grhsim32_assignment_eval grhsim32_score
    grhsim32_codepage grhsim32_collapse_retry)
