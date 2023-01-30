cmake_minimum_required(VERSION 3.15)
set (CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
set (CMAKE_LINKER_FLAGS_DEBUG "${CMAKE_LINKER_FLAGS_DEBUG} -fno-omit-frame-pointer -fsanitize=address")
project(uthreads)

set(CMAKE_CXX_STANDARD 11)

add_library(uthreads uthreads.h uthreads.cpp )

set_property(TARGET uthreads PROPERTY CXX_STANDARD 11)
target_compile_options(uthreads PUBLIC -Wall -Wextra)

add_subdirectory(tests)