package cmd

import (
	"bufio"
	"io/ioutil"
	"math/rand"
	"os"

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
				apply(task)
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
		var err error
		switch t.Kind {
		case "read":
			err = applyRead(t.Files)
		case "write":
			err = applyWrite(t.Files)
		}
		if err != nil {
			return err
		}
	}

	return nil
}

func applyRead(filesPath []string) error {
	for _, filePath := range filesPath {
		f, err := os.Open(filePath)
		if err != nil {
			return nil
		}
		defer f.Close()
		// read first 4 byte
		_, err = bufio.NewReader(f).Peek(4)
		if err != nil {
			return nil
		}
	}
	return nil
}

func applyWrite(filesPath []string) error {
	for _, filePath := range filesPath {
		content := make([]byte, 4)
		rand.Read(content)
		err := os.WriteFile(filePath, content, 0644)
		if err != nil {
			return nil
		}
	}
	return nil
}
