#include <unistd.h>
#include <fcntl.h>

int main(int argc, char **argv)
{
    openat(AT_FDCWD, "dir/file", 0);
    return 0;
}
