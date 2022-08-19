package cmd

import (
	"bufio"
	"io/ioutil"
	"math/rand"
	"os"
	"os/exec"
	"runtime"
	"sync"
	"syscall"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

var (
	tasksFilePath string
	rootCmd       = &cobra.Command{
		Use:   "loder",
		Short: "Apply a load to access os files and execute processes in respect to tasks file.",
		RunE: func(cmd *cobra.Command, args []string) error {
			path, err := cmd.Flags().GetString("tasks")
			if err != nil {
				return err
			}
			yfile, err := ioutil.ReadFile(path)
			if err != nil {
				return err
			}
			var tasks []Task
			err = yaml.Unmarshal(yfile, &tasks)
			if err != nil {
				return err
			}
			for _, task := range tasks {
				err = apply(task)
				if err != nil {
					return err
				}
			}
			return nil
		},
	}
)

func init() {
	rootCmd.PersistentFlags().StringVar(&tasksFilePath, "tasks", "./tasks.yml", "path to tasks yaml file")
}

func Execute() {
	err := rootCmd.Execute()
	if err != nil {
		os.Exit(1)
	}
}

type Task struct {
	Kind  string
	Files []string
	Scale int
}

func apply(t Task) error {
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
		}
		for _, filePath := range t.Files {
			err := taskFunc(filePath)
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
		err = applyExecuteSubproc(executablePath)
		wg.Done()
	}()
	return err
}

func applyCreateDelete(filePath string) error {
	f, err := os.Create(filePath)
	if err != nil {
		return err
	}
	f.Close()
	err = os.Remove(filePath)
	if err != nil {
		return err
	}
	return nil
}

func applyFork(filePath string) error {
	_, err := syscall.ForkExec(filePath, nil, nil)
	return err
}

func applyChmod(filePath string) error {
	err := os.Chmod(filePath, 644)
	return err
}

func applyChown(filePath string) error {
	err := os.Chown(filePath, -1, -1)
	return err
}
