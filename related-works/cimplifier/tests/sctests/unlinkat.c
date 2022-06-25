#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>

int main(int argc, char **argv)
{
    printf("%x\n",AT_FDCWD);
    //int dirfd = open("dir/foo", O_RDONLY);
    unlinkat(AT_FDCWD, "dir/file", 0);
    return 0;
}
