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
    int fd1 = open("file", O_CREAT | O_RDONLY);
    close(fd1);
    chmod("file", 777);
    chown("file", 1001, 0);
    lchown("file", 0, 0);
    truncate("file", 1024);
    mkdir("dir", 700);
    rmdir("dir");
    rename("file", "file2");
    link("file2", "file");
    unlink("file2");
    symlink("file", "file2");
    unlink("file2");

    // openat, mkdirat
    mkdirat(AT_FDCWD, "dir", 700);
    int dirfd2 = openat(AT_FDCWD, "dir", O_RDONLY);
    mkdirat(dirfd2, "foo", 700);
    int dirfd1 = openat(dirfd2, "foo", O_RDONLY);
    // linkat
    linkat(AT_FDCWD, "file", dirfd1, "file", 0);
    linkat(dirfd1, "file", AT_FDCWD, "file2", 0);
    linkat(dirfd1, "file", dirfd2, "file", 0);
    linkat(AT_FDCWD, "file", AT_FDCWD, "file3", 0);
    // unlinkat
    unlinkat(AT_FDCWD, "file3", 0);
    unlinkat(dirfd2, "file", 0);
    // renameat
    renameat(AT_FDCWD, "file2", AT_FDCWD, "file3");
    // renameat2 was not found in stdio.h as man page says
    // renameat2(AT_FDCWD, "file3", AT_FDCWD, "file2", 0);
    renameat(dirfd1, "file", dirfd2, "file");
    renameat(AT_FDCWD, "file3", dirfd1, "file");
    //symlinkat
    symlinkat("file", AT_FDCWD, "file2");
    symlinkat("file", dirfd2, "file2");
    return 0;
}
