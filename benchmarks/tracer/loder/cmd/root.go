package cmd

import (
	"bufio"
	"fmt"
	"io/fs"
	"io/ioutil"
	"math/rand"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

var (
	workers int
	runTime time.Duration
	rootCmd = &cobra.Command{
		Use:   "loder",
		Short: "Apply a load to access os files and execute processes in respect to tasks file.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {

			yfile, err := ioutil.ReadFile(args[0])
			if err != nil {
				return err
			}

			var tasks []Task
			err = yaml.Unmarshal(yfile, &tasks)
			if err != nil {
				return err
			}

			sigs := make(chan os.Signal, 1)
			signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM, syscall.SIGQUIT)
			shutdown := make(chan struct{})

			wg := sync.WaitGroup{}
			wg.Add(workers)

			startCollector(&wg, shutdown)
			for i := 0; i < workers; i++ {
				go func(workerId int) {
				infinite:
					for {
						select {
						case <-shutdown:
							break infinite
						default:
							s := time.Now()
							for _, task := range tasks {
								err = apply(task, workerId)
								if err != nil {
									fmt.Printf("error on %d: ", workerId)
									fmt.Println(err.Error())
									close(sigs)
									break infinite
								}
							}
							observeDuration(time.Since(s))
						}
					}
					wg.Done()
				}(i)
			}

			select {
			case <-time.After(runTime):
			case <-sigs:
			}
			close(shutdown)
			wg.Wait()
			return nil
		},
	}
)

func init() {
	rootCmd.Flags().IntVar(&workers, "worker", 1, "number of concurrent workers.")
	rootCmd.Flags().DurationVar(&runTime, "run-time", time.Minute, "how much time loder should work")
}

func Execute() {
	err := rootCmd.Execute()
	if err != nil {
		os.Exit(1)
	}
}

func TruncatingSprintf(str string, args ...interface{}) string {
	n := strings.Count(str, "%d")
	return fmt.Sprintf(str, args[0:n]...)
}

type Task struct {
	Kind  string
	Files []string
	Scale int
}

func apply(t Task, workerId int) error {
	for i := 1; i <= t.Scale; i++ {
		taskFunc := func(string) error { return nil }
		switch t.Kind {
		case "read":
			taskFunc = applyRead
		case "write":
			taskFunc = applyWrite
		case "execute-subproc":
			taskFunc = applyExecuteSubproc
		case "execute-subthread":
			taskFunc = applyExecuteSubthread
		case "create-delete":
			taskFunc = applyCreateDelete
		case "fork":
			taskFunc = applyFork
		case "chmod":
			taskFunc = applyChmod
		case "chown":
			taskFunc = applyChown
		case "mkdir":
			taskFunc = applyMkdir
		case "remove":
			taskFunc = remove
		case "rename":
			taskFunc = rename
		case "hard-link":
			taskFunc = hardLink
		case "soft-link":
			taskFunc = softLink
		}
		for _, filePath := range t.Files {
			p := TruncatingSprintf(filePath, workerId)
			err := taskFunc(p)
			if err != nil {
				return err
			}
		}
	}

	return nil
}

func applyRead(filePath string) error {
	f, err := os.Open(filePath)
	if err != nil {
		return nil
	}
	defer f.Close()
	// read first 4 byte
	_, err = bufio.NewReader(f).Peek(4)
	if err != nil {
		return err
	}
	return nil
}

func applyWrite(filePath string) error {
	content := make([]byte, 4)
	rand.Read(content)
	err := os.WriteFile(filePath, content, 0644)
	if err != nil {
		return err
	}
	return nil
}

func applyExecuteSubproc(executablePath string) error {
	err := exec.Command(executablePath).Run()
	if err != nil {
		return err
	}
	return nil
}

func applyExecuteSubthread(executablePath string) error {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	var err error
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		applyExecuteSubproc(executablePath)
		wg.Done()
	}()
	wg.Wait()
	return err
}

func applyCreateDelete(filePath string) error {
	f, err := os.Create(filePath)
	if err != nil {
		return err
	}
	err = f.Close()
	if err != nil {
		return err
	}
	return os.Remove(filePath)
}

func applyFork(filePath string) error {
	pid, err := syscall.ForkExec(filePath, nil, nil)
	if err != nil {
		return err
	}
	var wstatus syscall.WaitStatus
	_, err = syscall.Wait4(pid, &wstatus, 0, nil)
	return err
}

func applyChmod(filePath string) error {
	return os.Chmod(filePath, 0644)
}

func applyChown(filePath string) error {
	return os.Chown(filePath, -1, -1)
}

func applyMkdir(filePath string) error {
	return os.Mkdir(filePath, fs.FileMode(0777))
}

func remove(filePath string) error {
	return os.Remove(filePath)
}

func rename(filePath string) error {
	return os.Rename(filePath, filePath+"-renamed")
}

func hardLink(filePath string) error {
	return os.Link(filePath, filePath+"-hard-link")
}

func softLink(filePath string) error {
	return os.Symlink(filePath, filePath+"-soft-link")
}
