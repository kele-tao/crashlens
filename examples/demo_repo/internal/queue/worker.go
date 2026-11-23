package queue

import (
	"fmt"
	"sync"
)

type Job struct {
	Name string
}

type Worker struct {
	mu   sync.Mutex
	jobs []*Job
}

func (w *Worker) Enqueue(job *Job) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.jobs = append(w.jobs, job)
}

func (w *Worker) Run() {
	for _, job := range w.jobs {
		fmt.Println(job.Name)
	}
}
