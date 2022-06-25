#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <stdio.h>

// ignore all f* calls as file descriptor was already created
// ignore creat as result is zero-len file regardless of previous existence 
// renameat2 with RENAME_EXCHANGE requires both paths to exist: not handled
// linkat: AT_EMPTY_PATH flag changes semantics of the function: not handled
// symlink can be ignored. The only effect of existing files may be when target
// exists

int main(int argc, char **argv)
{

    int dirfd2 = openat(AT_FDCWD, "dir", O_RDONLY);
    int dirfd1 = openat(dirfd2, "foo", O_RDONLY);
    renameat(dirfd2, "file", dirfd1, "file2");
    return 0;
}
