#define _GNU_SOURCE
#include <unistd.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/signalfd.h>
#include <signal.h>
#include <poll.h>
#include <dirent.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>

/* to make this work on containers with old libc */
/* use of signalfd requires glibc>2.7 */
__asm__(".symver memcpy,memcpy@GLIBC_2.2.5");

#define UNUSED(expr) do { (void)(expr); } while (0)

//#define SOCK_PATH "/tmp/cexec.sock"
#define SOCK_PATH_SIZE 255
#define LISTEN_BACKLOG 50
/* keep buf size at least 128 (siginfo) or the expected size of cwd */
#define BUF_SIZE 512

#define handle_error(msg) do { perror(msg); exit(EXIT_FAILURE); } while(0)

/* assume buf is big enough. We will have six uid_t/gid_t values, each of which
 * is 32-bit, i.e., total of 24 bytes.
 * also add umask... total of 28 bytes now.
 */
int get_credentials(char *buf) {
    uid_t ruid, euid, suid;
    gid_t rgid, egid, sgid;
    getresuid(&ruid, &euid, &suid);
    getresgid(&rgid, &egid, &sgid);
    *(uid_t *)buf = ruid;
    *((uid_t *)buf + 1) = euid;
    *((uid_t *)buf + 2) = suid;
    buf += 3 * sizeof(uid_t);
    *(gid_t *)buf = rgid;
    *((gid_t *)buf + 1) = egid;
    *((gid_t *)buf + 2) = sgid;
    buf += 3 * sizeof(gid_t);
    mode_t mask = umask(0);
    umask(mask);
    *(mode_t *)buf = mask;
    return 3*sizeof(uid_t) + 3*sizeof(gid_t) + sizeof(mode_t);
}


void send_fds(int sfd, struct msghdr *msg) {
    struct cmsghdr *cmsg;
    char cmsgbuf[CMSG_SPACE(sizeof(int))];
    msg->msg_control = cmsgbuf;
    msg->msg_controllen = sizeof(cmsgbuf);
    cmsg = CMSG_FIRSTHDR(msg);
    cmsg->cmsg_level = SOL_SOCKET;
    cmsg->cmsg_type = SCM_RIGHTS;
    cmsg->cmsg_len = CMSG_LEN(sizeof(int));
    int *fdptr = (int *)CMSG_DATA(cmsg);
    msg->msg_controllen = cmsg->cmsg_len;

    char *buf = (char *)(msg->msg_iov->iov_base);

    DIR *dir = opendir("/proc/self/fd");
    if (!dir)
        handle_error("/proc/self/fd");
    int dirno = dirfd(dir), fd;
    struct dirent *entry;
    char *endptr;
    while ((entry = readdir(dir))) {
        fd = (int)strtol(entry->d_name, &endptr, 0);
        if (endptr == entry->d_name /* . or .. entry */
                || fd == dirno || fd == sfd)
            continue;

        *fdptr = fd;
        *(int *)buf = fd;
        msg->msg_iov->iov_len = sizeof(int);
        if (sendmsg(sfd, msg, 0) == -1)
            handle_error("sendmsg send_fds");
    }
    closedir(dir);

    msg->msg_control = NULL;
    msg->msg_controllen = 0;
    strcpy(buf, "donefd");
    msg->msg_iov->iov_len = strlen("donefd") + 1;
    if (sendmsg(sfd, msg, 0) == -1)
        handle_error("sendmsg send_fds donefd");
}

void charpp_size(char* arr[], unsigned *size, size_t *numchars) {
    char **i;
    unsigned arr_size = 0;
    size_t allchars_size = 0;
    for (i = arr; *i != NULL; ++i) {
        allchars_size += strlen(*i) + 1; /* +1 for the \0 byte */
        arr_size += 1;
    }
    arr_size += 1; /* for the final NULL */
    *size = arr_size;
    *numchars = allchars_size;
}

/* The function below assumes the msghdr as laid out in the caller; it is
 * not general.
 */
void send_arr(char* arr[], int sfd, struct msghdr *message, const size_t buf_size) {
    char *buf = (char *)(message->msg_iov->iov_base);
    size_t copied = 0, buf_filled = 0, to_copy;

    message->msg_iov->iov_len = buf_size;
    while (*arr) {
        to_copy = strlen(*arr) + 1 - copied;
        if (to_copy <= buf_size - buf_filled) {
            memcpy(buf + buf_filled, *arr + copied, to_copy);
            copied = 0;
            buf_filled += to_copy;
            arr++;
        } else {
            memcpy(buf + buf_filled, *arr + copied, buf_size - buf_filled);
            copied += buf_size - buf_filled;
            buf_filled = 0;
            if (sendmsg(sfd, message, 0) == -1)
                handle_error("sendmsg send_arr");
        }
    }
    if (buf_filled) {
        message->msg_iov->iov_len = buf_filled;
        if (sendmsg(sfd, message, 0) == -1)
            handle_error("sendmsg send_arr");
    }
}

void communicate(int sfd, sigset_t *sigmask, sigset_t *oldsigmask,
        char**argv, char**envp) {
    char buf[BUF_SIZE];
    struct msghdr message;
    struct iovec iov;
    unsigned len;
    size_t numchars;

    iov.iov_base = buf;
    iov.iov_len = BUF_SIZE;

    memset(&message, 0, sizeof(struct msghdr));
    message.msg_name = NULL;
    message.msg_namelen = 0;
    message.msg_iov = &iov;
    message.msg_iovlen = 1;
    message.msg_control = NULL;
    message.msg_controllen = 0;

    /* exe We assume proc is available */
    ssize_t exelen = readlink("/proc/self/exe", buf, BUF_SIZE-1);
    if (exelen == -1 || exelen == BUF_SIZE-1)
        handle_error("readlink");
    buf[exelen] = '\0';
    iov.iov_len = exelen + 1;
    if (sendmsg(sfd, &message, 0) == -1)
        handle_error("readlink exe");
    
    /* cwd */
    if (getcwd(buf, BUF_SIZE-1) == NULL)
        handle_error("getcwd");
    iov.iov_len = strlen(buf)+1;
    if (sendmsg(sfd, &message, 0) == -1)
        handle_error("sendmsg getcwd");

    /* user and group identifiers */
    iov.iov_len = get_credentials(buf);
    if (sendmsg(sfd, &message, 0) == -1)
        handle_error("sendmsg credentials");

    /* argv */
    charpp_size(argv, &len, &numchars);
    *(uintmax_t *)buf = (uintmax_t)len;
    *((uintmax_t *)buf + 1) = (uintmax_t)numchars;
    iov.iov_len = 2 * sizeof(uintmax_t);
    if (sendmsg(sfd, &message, 0) == -1)
        handle_error("sendmsg argv size");
    send_arr(argv, sfd, &message, BUF_SIZE);

    /* envp */
    charpp_size(envp, &len, &numchars);
    *(uintmax_t *)buf = (uintmax_t)len;
    *((uintmax_t *)buf + 1) = (uintmax_t)numchars;
    iov.iov_len = 2 * sizeof(uintmax_t);
    if (sendmsg(sfd, &message, 0) == -1)
        handle_error("sendmsg argv size");
    send_arr(envp, sfd, &message, BUF_SIZE);

    /* file descriptors */
    send_fds(sfd, &message);

    /* set up signalfd and polling on signalfd, sfd */
    int sigfd = signalfd(-1, sigmask, 0);
    if (sigfd == -1)
        handle_error("signalfd");
    struct signalfd_siginfo fdsi;

    struct pollfd ufds[2];
    ufds[0] = (struct pollfd) { .fd = sigfd, .events = POLLIN };
    ufds[1] = (struct pollfd) { .fd = sfd, .events = POLLIN };
    for (;;) {
        if (poll(ufds, 2, -1) == -1)
            handle_error("poll");
        if (ufds[0].revents & POLLIN) {
            if (read(sigfd, &fdsi, sizeof(struct signalfd_siginfo))
                    != sizeof(struct signalfd_siginfo))
                handle_error("read siginfo");
            /* check if these signals were sent using kill or sigqueue from
             * another process */
            if (fdsi.ssi_code == SI_USER || fdsi.ssi_code == SI_QUEUE) {
                iov.iov_base = &fdsi;
                iov.iov_len = sizeof(struct signalfd_siginfo);
                if (sendmsg(sfd, &message, 0) == -1)
                    handle_error("sendmsg siginfo");
            }
        }
        if (ufds[1].revents & POLLIN) {
            /* iov_len was changed when sending */
            iov.iov_base = buf;
            iov.iov_len = BUF_SIZE;
            ssize_t nread = recvmsg(sfd, &message, 0);
            if (nread == -1)
                handle_error("recvmsg sig");
            if (nread == 0) /* server shutdown; shouldn't happen */
                exit(10);
            /* we shall exit and possibly signal ourselves. Unblock signals */
            if (sigprocmask(SIG_BLOCK, oldsigmask, NULL) == -1)
                handle_error("sigprocmask set");
            int exited = *(int *)buf;
            if (exited)
                exit(*((int *)buf + 1));
            int signaled = *((int *)buf + 2);
            if (signaled)
                raise(*((int *)buf + 3));
            /* anything else should not happen assuming no ptrace */
            exit(10);
        }
        if (ufds[1].revents & (POLLHUP | POLLRDHUP | POLLERR)) {
            /* server shutdown; shouldn't happen */
            exit(10);
        }
    }
}

/* this function does not check length of sockpath buffer */
void make_sock_path(char *exepath, char *sockpath) {
    exepath++; /* ignore the leading / */
    strcpy(sockpath, "/walls/");
    sockpath += strlen("/walls/");
    char chr = *exepath;
    while(chr != '\0') {
        if (chr == '/') {
            *sockpath = '_';
        } else {
            *sockpath = chr;
        }
        sockpath++;
        exepath++;
        chr = *exepath;
    }
    strcpy(sockpath, "/cexec.sock");
}


int main(int argc, char *argv[], char *envp[]) {
    UNUSED(argc);

    /* mask all signals possible, we will handle them after initial setup */
    sigset_t sigmask, oldsigmask;
    sigfillset(&sigmask);
    if (sigprocmask(SIG_BLOCK, &sigmask, &oldsigmask) == -1)
        handle_error("sigprocmask set");

    int sfd;
    struct sockaddr_un addr;
    socklen_t addr_size;
    
    sfd = socket(AF_UNIX, SOCK_SEQPACKET, 0);
    if (sfd == -1)
        handle_error("socket");

    char buf[BUF_SIZE];
    ssize_t exelen = readlink("/proc/self/exe", buf, BUF_SIZE-1);
    if (exelen == -1 || exelen == BUF_SIZE-1)
        handle_error("readlink");
    buf[exelen] = '\0';

    char sock_path[SOCK_PATH_SIZE];
    make_sock_path(buf, sock_path);

    /* Clear structure */
    memset(&addr, 0, sizeof(struct sockaddr_un));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, sock_path, sizeof(addr.sun_path) - 1);

    addr_size = sizeof(struct sockaddr_un);
    if (connect(sfd, (struct sockaddr *) &addr, addr_size) == -1)
        handle_error("connect");

    communicate(sfd, &sigmask, &oldsigmask, argv, envp);

    close(sfd);

    return 0;
}

