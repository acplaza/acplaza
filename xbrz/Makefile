CPPFLAGS=-std=gnu++17 -O3
CPP=c++

xbrz.so: xbrz.cpp
	$(CPP) -fPIC -shared $(CPPFLAGS) -o xbrz.so xbrz.cpp

clean:
	rm -f xbrz.so
