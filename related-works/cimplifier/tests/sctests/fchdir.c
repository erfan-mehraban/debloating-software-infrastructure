#include <unistd.h>
#include <fcntl.h>

int main(int argc, char **argv)
{
    int dirfd = open("dir/foo", O_RDONLY);
    fchdir(dirfd);
    unlinkat(AT_FDCWD, "file", 0);
    return 0;
}
