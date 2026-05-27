cmake_minimum_required(VERSION 3.20)
project(topo_graph_partition_harness VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Threads REQUIRED)

if (NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
file(MAKE_DIRECTORY "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}")

add_library(tgp_harness STATIC
    lib/json.cpp
    lib/graph_io.cpp
    lib/quotient_graph.cpp
    lib/validate_graph.cpp
    lib/validate_partition.cpp
    lib/score_partition.cpp
    lib/brute_force_oracle.cpp
    lib/experiment.cpp
    algorithms/topo_window.cpp
)

target_include_directories(tgp_harness
    PUBLIC
        include
)

target_link_libraries(tgp_harness PUBLIC Threads::Threads)

add_library(tgp::harness ALIAS tgp_harness)

function(add_tgp_cli name source)
    add_executable(${name} ${source})
    target_link_libraries(${name} PRIVATE tgp_harness)
endfunction()

add_tgp_cli(tgp_validate_graph app/tgp_validate_graph.cpp)
add_tgp_cli(tgp_validate_partition app/tgp_validate_partition.cpp)
add_tgp_cli(tgp_score_partition app/tgp_score_partition.cpp)
add_tgp_cli(tgp_oracle app/tgp_oracle.cpp)
add_tgp_cli(tgp_run_experiment app/tgp_run_experiment.cpp)
