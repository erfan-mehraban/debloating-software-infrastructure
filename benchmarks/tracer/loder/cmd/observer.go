package cmd

import (
	"fmt"
	"sync"
	"time"
)

var durationChan chan time.Duration

func startCollector(wg *sync.WaitGroup, shutdown chan struct{}) {
	durationChan = make(chan time.Duration, 1000)
	wg.Add(1)
	go func() {
		counter := 0
		sum := time.Duration(0)
	collectorInfinite:
		for {
			select {
			case d := <-durationChan:
				sum += d
				counter += 1
			case <-shutdown:
				fmt.Printf("avg: %s\n", sum/time.Duration(counter))
				fmt.Printf("count: %d\n", counter)
				wg.Done()
				break collectorInfinite
			}
		}
	}()
}

func observeDuration(d time.Duration) {
	durationChan <- d
}
