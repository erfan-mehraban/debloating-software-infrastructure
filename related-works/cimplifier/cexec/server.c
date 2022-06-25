#define _GNU_SOURCE
#include <unistd.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/signalfd.h>
#include <signal.h>
#include <poll.h>
#include <sys/wait.h>
#include <errno.h>
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
#define BUF_SIZE 512

#define handle_error(msg) do { perror(msg); exit(EXIT_FAILURE); } while(0)

void graft(char *exe, int *orig_fds, int *fds, int fds_recvd, char **argv, char **envp) {
    for (int i = 0; i < fds_recvd; ++i) {
        if (dup2(fds[i], orig_fds[i]) == -1)
            handle_error("dup2");
        close(fds[i]);
    }
    if (execve(exe, argv, envp) == -1)
        handle_error("execve");
}

/* user ids, group ids, umask. umask is not a credential */
void apply_credentials(char *buf) {
    uid_t ruid, euid, suid;
    gid_t rgid, egid, sgid;
    ruid = *(uid_t *)buf;
    euid = *((uid_t *)buf + 1);
    suid = *((uid_t *)buf + 2);
    buf += 3 * sizeof(uid_t);
    rgid = *(gid_t *)buf;
    egid = *((gid_t *)buf + 1);
    sgid = *((gid_t *)buf + 2);
    buf += 3 * sizeof(gid_t);
    mode_t mask = *(mode_t *)buf;
    printf("%u %u %u %u %u %u %o\n", ruid, euid, suid, rgid, egid, sgid, mask);
    if (setresgid(rgid, egid, sgid))
        handle_error("setresgid");
    if (setresuid(ruid, euid, suid) == -1)
        handle_error("setresuid");
    umask(mask);
}

void print_charpp(char **arr) {
    while (*arr) {
        printf("%s ", *arr);
        ++arr;
    }
    printf("\n");
}

void monitor(int cfd) {
    char buf[BUF_SIZE];
    char exe[BUF_SIZE];
    ssize_t nread;
    struct msghdr message;
    struct iovec iov;

    unsigned argv_size, envp_size, charp_copied;
    size_t argv_numchars, envp_numchars, chars_copied;
    char **argv, **envp;
    char *argv_str, *envp_str;


    memset(&message, 0, sizeof(struct msghdr));
    message.msg_name = NULL;
    message.msg_namelen = 0;
    message.msg_iov = &iov;
    message.msg_iovlen = 1;
    message.msg_control = NULL;
    message.msg_controllen = 0;

    /* exe */
    iov.iov_base = exe;
    iov.iov_len = BUF_SIZE;
    nread = recvmsg(cfd, &message, 0);
    if (nread == -1)
        handle_error("recvmsg exe");
    printf("%s\n", exe);

    iov.iov_base = buf;
    iov.iov_len = BUF_SIZE;

    /* cwd */
    nread = recvmsg(cfd, &message, 0);
    if (nread == -1)
        handle_error("recvmsg chdir");
    printf("%s\n", buf);
    if (chdir(buf) == -1)
        /* We could get ENOENT because the dir does not exist in target
         * container. If this happens, we should fix the container creation
         * code.
         */
        handle_error("chdir");

    /* user and group identifiers */
    nread = recvmsg(cfd, &message, 0);
    if (nread == -1)
        handle_error("recvmsg credentials");
    apply_credentials(buf);

    /* argv */
    nread = recvmsg(cfd, &message, 0);
    if (nread == -1)
        handle_error("recvmsg argv");
    argv_size = (unsigned)*(uintmax_t *)buf;
    argv_numchars = (size_t)*((uintmax_t *)buf + 1);
    argv_str = (char *)malloc(argv_numchars);
    argv = (char **)malloc(argv_size*sizeof(char *));
    printf("%u %zu\n", argv_size, argv_numchars);
    chars_copied = 0;
    while (chars_copied < argv_numchars) {
        nread = recvmsg(cfd, &message, 0);
        if (nread == -1)
            handle_error("recvmsg argv");
        memcpy(argv_str + chars_copied, buf, nread);
        chars_copied += nread;
    }
    charp_copied = 0;
    while (1) {
        argv[charp_copied] = argv_str;
        ++charp_copied;
        if (charp_copied == argv_size - 1) /* argv[-1] is for NULL */
            break;
        argv_str += strlen(argv_str) + 1;
    }
    argv[charp_copied] = NULL;
    
    /* envp */
    /* todo we can outline the code for argv/envp in a function */
    nread = recvmsg(cfd, &message, 0);
    if (nread == -1)
        handle_error("recvmsg envp");
    envp_size = (unsigned)*(uintmax_t *)buf;
    envp_numchars = (size_t)*((uintmax_t *)buf + 1);
    envp_str = (char *)malloc(envp_numchars);
    envp = (char **)malloc(envp_size*sizeof(char *));
    printf("%u %zu\n", envp_size, envp_numchars);
    chars_copied = 0;
    while (chars_copied < envp_numchars) {
        nread = recvmsg(cfd, &message, 0);
        if (nread == -1)
            handle_error("recvmsg envp");
        memcpy(envp_str + chars_copied, buf, nread);
        chars_copied += nread;
    }
    charp_copied = 0;
    while (1) {
        envp[charp_copied] = envp_str;
        ++charp_copied;
        if (charp_copied == envp_size - 1) /* envp[-1] is for NULL */
            break;
        envp_str += strlen(envp_str) + 1;
    }
    envp[charp_copied] = NULL;

    print_charpp(argv);
    print_charpp(envp);


    /* file descriptors */
    /* We will accumulate all file descriptors in two arrays. After fork,
     * we will apply them to our new process and close them in the original
     * process.
     */

    /* set up cmsg for file descriptors */
    struct cmsghdr *cmsg;
    char cmsgbuf[CMSG_SPACE(sizeof(int))];
    message.msg_control = cmsgbuf;
    message.msg_controllen = sizeof(cmsgbuf);
    cmsg = CMSG_FIRSTHDR(&message);
    int *fdptr = (int *)CMSG_DATA(cmsg);

    int fds_size = 8;
    int *orig_fds = (int *) malloc(fds_size * sizeof(orig_fds));
    int *fds = (int *) malloc(fds_size * sizeof(fds));
    int fds_recvd = 0;

    nread = recvmsg(cfd, &message, 0);
    if (nread == -1)
        handle_error("recvmsg envp");
    while (strcmp(buf, "donefd")) {
        fds_recvd++;
        if (fds_recvd == fds_size) {
            fds_size *= 2;
            orig_fds = (int *) realloc(orig_fds, fds_size * sizeof(orig_fds));
            fds = (int *) realloc(fds, fds_size * sizeof(fds));
        }
        fds[fds_recvd-1] = *fdptr;
        orig_fds[fds_recvd-1] = *(int *)buf;
        nread = recvmsg(cfd, &message, 0);
        if (nread == -1)
            handle_error("recvmsg envp");
    }

    for (int i = 0; i < fds_recvd; ++i) {
        printf("orig:%d this:%d\n", orig_fds[i], fds[i]);
    }

    /* prepare for forking/execing */
    /* mark socket descriptor for auto-close on exec */
    if (fcntl(cfd, F_SETFD, FD_CLOEXEC) == -1)
        handle_error("fcntl FD_CLOEXEC");

    /* block SIGCHLD so we can use signalfd. Do before fork so that we do
     * not miss that signal. Unblock it later in the child.
     */
    sigset_t sigmask, oldsigmask;
    sigemptyset(&sigmask);
    sigaddset(&sigmask, SIGCHLD);
    if (sigprocmask(SIG_BLOCK, &sigmask, &oldsigmask) == -1)
        handle_error("sigprocmask set");

    /* fork now */
    pid_t pid;
    if ((pid = fork()) == -1)
        handle_error("fork");
    if (!pid) {
        /* revert to original sigmask. We should probably get the sigmask here
         * from the client todo. */
        if (sigprocmask(SIG_BLOCK, &oldsigmask, NULL) == -1)
            handle_error("sigprocmask unset");
        graft(exe, orig_fds, fds, fds_recvd, argv, envp);
    }

    /* graft() never returns */
    /* close the file descriptors received here and free the fd arrays*/
    for (int i = 0; i < fds_recvd; ++i)
        close(fds[i]);
    free(orig_fds);
    free(fds);

    /* setup signalfd, poll structs, and start poll on sigfd, cfd */
    int sigfd = signalfd(-1, &sigmask, 0);
    if (sigfd == -1)
        handle_error("signalfd");

    struct pollfd ufds[2];
    ufds[0] = (struct pollfd) { .fd = sigfd, .events = POLLIN };
    ufds[1] = (struct pollfd) { .fd = cfd, .events = POLLIN };
    for (;;) {
        if (poll(ufds, 2, -1) == -1)
            handle_error("poll");
        if (ufds[0].revents & POLLIN) {
            /* we will only ever have one child. Not sure how to not receive
             * SIGCHLD here for stop/continue */
            int status;
            int retval = waitpid(pid, &status, WNOHANG);
            if (retval == -1)
                handle_error("waitpid");
            if (retval > 0) {
                int exited = WIFEXITED(status), signaled = WIFSIGNALED(status);
                *(int *)buf = exited;
                *((int *)buf + 1) = exited ? WEXITSTATUS(status) : 0;
                *((int *)buf + 2) = signaled;
                *((int *)buf + 3) = signaled ? WTERMSIG(status) : 0;
                iov.iov_base = buf;
                iov.iov_len = 4 * sizeof(int);
                if (sendmsg(cfd, &message, 0) == -1)
                    handle_error("sendmsg SIGCHLD");
                exit(0);
            }
            /* ignore the retval == 0 case... it was likely a stop/continue */
        }
        if (ufds[1].revents & POLLIN) {
            struct signalfd_siginfo fdsi;
            iov.iov_base = &fdsi;
            iov.iov_len = sizeof(struct signalfd_siginfo);
            nread = recvmsg(cfd, &message, 0);
            if (nread == -1)
                handle_error("recvmsg sig");
            if (nread == 0) { /* client shutdown */
                if (kill(pid, SIGKILL) == -1) {
                    if (errno == ESRCH)
                        /* child already dead; container's init will reap */
                        exit(0);
                    handle_error("kill SIGKILL");
                }
                exit(0);
            }
            /* normal signaling from client */
            /* Ideally, we should also set the correct sender credentials
             * (perhaps the uid only, not the pid) when sending a kill or
             * sigqueue signal. For sigqueue, we may be able to use the
             * underlying rt_sigqueueinfo syscall to set the uid, but for kill,
             * we don't know of a way yet. The way to work out both may be to
             * just set the parent real uid to the right uid before sending
             * the signal. */
            int rv;
            if (fdsi.ssi_code == SI_USER)
                rv = kill(pid, fdsi.ssi_signo);
            else {
                /* below we set ssi_ptr instead of ssi_int; both are inferred
                 * from the same sigqueue value, which was a union, so we choose
                 * the wider of the two members. This will work correctly even
                 * if recepient expects int. */ 
                union sigval value;
                value.sival_ptr = (void *)fdsi.ssi_ptr;
                rv = sigqueue(pid, fdsi.ssi_signo, value);
            }
            if (rv == -1)
                if (errno != ESRCH) /* on ESRCH we'll soon receive SIGCHLD */
                    handle_error("kill/sigqueue");
        }
        if (ufds[1].revents & (POLLHUP | POLLRDHUP | POLLERR)) {
            if (kill(pid, SIGKILL) == -1) {
                if (errno == ESRCH)
                    /* child already dead; container's init will reap */
                    exit(0); 
                handle_error("kill SIGKILL");
            }
        }
    } 

    close(cfd);
    exit(0);
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

int main(int argc, char *argv[]) {
    UNUSED(argc);
    UNUSED(argv);

    /* disable zombie creation; this is POSIX.1-2001 */
    if (signal(SIGCHLD, SIG_IGN) == SIG_ERR)
        handle_error("sigchld");

    int sfd, cfd;
    struct sockaddr_un my_addr, peer_addr;
    socklen_t peer_addr_size;
    pid_t pid;

    sfd = socket(AF_UNIX, SOCK_SEQPACKET, 0);
    if (sfd == -1)
        handle_error("socket");

    char sock_path[SOCK_PATH_SIZE];
    make_sock_path(argv[1], sock_path);
    unlink(sock_path); /* this may fail but does not hurt */

    /* Clear structure */
    memset(&my_addr, 0, sizeof(struct sockaddr_un));
    my_addr.sun_family = AF_UNIX;
    strncpy(my_addr.sun_path, sock_path, sizeof(my_addr.sun_path) - 1);

    /* set umask to 0 to allow world-writable socket, solution from mysql */
    mode_t mask = umask(0);
    if (bind(sfd, (struct sockaddr *) &my_addr,
            sizeof(struct sockaddr_un)) == -1)
        handle_error("bind");
    umask(mask);

    if (listen(sfd, LISTEN_BACKLOG) == -1)
        handle_error("listen");

    peer_addr_size = sizeof(struct sockaddr_un);
    while ((cfd = accept(sfd, (struct sockaddr *) &peer_addr,
                    &peer_addr_size)) != -1) {
        if ((pid = fork()) == -1)
            handle_error("fork");
        if (!pid) {
            close(sfd);
            /* set SIGCHLD to default; we want to receive this sig in child */
            if (signal(SIGCHLD, SIG_DFL) == SIG_ERR)
                handle_error("sigchld");
            monitor(cfd);
        }
        /* the controller function never returns */
        close(cfd);
    }
    handle_error("accept");

    /* tear down */
    close(sfd);
    unlink(sock_path);
    return 0;
}

