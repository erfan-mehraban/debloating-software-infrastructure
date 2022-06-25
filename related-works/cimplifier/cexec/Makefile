# disabling strict aliasing optimization as we often write different types
# to the same buffer. It doesn't look like our code will benefit much from this
# anyway
CFLAGS=-std=c99 -Wall -Wextra -pedantic -Wshadow -O2 -fno-strict-aliasing

all: server client
