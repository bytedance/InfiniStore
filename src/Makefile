CXX = g++
CXXFLAGS = -std=c++17 -Wall -O3 -g

INCLUDES = -I/usr/local/
LDFLAGS = -rdynamic
LIBS = -luv -libverbs -lfmt -lboost_stacktrace_basic -ldl
PYTHON=python3
PYBIND11_INCLUDES = $(shell $(PYTHON) -m pybind11 --includes)
PYTHON_EXTENSION_SUFFIX = $(shell $(PYTHON)-config --extension-suffix)

PYBIND_TARGET= _infinistore$(PYTHON_EXTENSION_SUFFIX)

SOURCES := $(wildcard *.cpp)
OBJECTS = $(SOURCES:.cpp=.o)

all:$(PYBIND_TARGET)

manylinux: PYTHON ?= python3.11
manylinux: CXXFLAGS = -std=c++17 -g -O3 -Wall
manylinux: LIBS = -luv -libverbs -lfmt -lboost_stacktrace_basic -ldl
manylinux: INCLUDES += -I/usr/local/include
manylinux: PYBIND11_INCLUDES = $(shell $(PYTHON) -m pybind11 --includes)
manylinux: PYTHON_EXTENSION_SUFFIX = $(shell $(PYTHON)-config --extension-suffix)
manylinux: PYBIND_TARGET = _infinistore$(PYTHON_EXTENSION_SUFFIX)
manylinux: $(PYBIND_TARGET)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) -MMD -MP -fPIC -c $< -o $@

%_generated.h: %.fbs
	flatc --cpp $<

-include $(OBJECTS:.o=.d)

$(PYBIND_TARGET): pybind.cpp libinfinistore.o utils.o protocol.o infinistore.o log.o ibv_helper.o mempool.o rdma.o
	$(CXX) $(CXXFLAGS) $(INCLUDES) --shared -fPIC $(PYBIND11_INCLUDES) $^ \
	-o $(PYBIND_TARGET) $(LDFLAGS) $(LIBS)
	rm -rf ../infinistore/$(PYBIND_TARGET)
	cp $(PYBIND_TARGET) ../infinistore/


.PHONY: clean test
clean:
	rm -rf *.so *.o *.d test_client
