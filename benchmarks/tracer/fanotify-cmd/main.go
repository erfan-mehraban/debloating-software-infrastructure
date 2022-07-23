package main

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/docker-slim/docker-slim/pkg/third_party/madmo/fanotify"
)

func main() {

	args := os.Args[2:]
	c := exec.Command(os.Args[1], args...)

	nd, err := fanotify.Initialize(fanotify.FAN_CLASS_NOTIF|fanotify.FAN_NONBLOCK|fanotify.FAN_CLOEXEC|fanotify.FAN_UNLIMITED_QUEUE|fanotify.FAN_UNLIMITED_MARKS, os.O_RDONLY)
	if err != nil {
		panic(err)
	}

	// todo: find a solution to watch all subdir tree without mounting.
	err = nd.Mark(fanotify.FAN_MARK_ADD|fanotify.FAN_MARK_MOUNT,
		fanotify.FAN_MODIFY|fanotify.FAN_ACCESS|fanotify.FAN_OPEN|fanotify.FAN_ONDIR, -1, "/")
	if err != nil {
		panic(err)
	}

	err = nd.Mark(fanotify.FAN_MARK_ADD|fanotify.FAN_MARK_IGNORED_MASK,
		fanotify.FAN_MODIFY|fanotify.FAN_ACCESS|fanotify.FAN_OPEN|fanotify.FAN_ONDIR|fanotify.FAN_EVENT_ON_CHILD, -1, "/proc/")
	if err != nil {
		panic(err)
	}

	procEndSignal := make(chan struct{})
	c.Start()
	go func() {
		c.Wait()
		close(procEndSignal)
	}()

	for {

		data, err := nd.GetEvent()
		if err != nil {
			panic(err)
		}

		path, err := os.Readlink(fmt.Sprintf("/proc/self/fd/%d", data.File.Fd()))
		if err != nil {
			panic(err)
		}

		if c.Process.Pid == int(data.Pid) {
			// if (data.Mask & fanotify.FAN_OPEN) == fanotify.FAN_OPEN {
			// 	print("FAN_OPEN ")
			// }
			// if (data.Mask & fanotify.FAN_ACCESS) == fanotify.FAN_ACCESS {
			// 	print("FAN_ACCESS ")
			// }
			// if (data.Mask & fanotify.FAN_MODIFY) == fanotify.FAN_MODIFY {
			// 	print("FAN_MODIFY ")
			// }
			println(path)
		}

		data.File.Close()

		shouldBreak := false
		select {
		case <-procEndSignal:
			shouldBreak = true
		default:
		}
		if shouldBreak {
			break
		}
	}
}
