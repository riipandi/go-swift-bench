// sampler: membaca cgroup v2 dan /proc tiap detik untuk container target, menulis CSV.
// probe  : polling /healthz (10 ms), latensi request pertama, burst request, dan GET sederhana.
//
//	sampler sample --out FILE [--interval 1s] --target nama:cid:pid[:noproc] ...
//	sampler probe wait|first|burst|get|now ...
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "pakai: sampler sample|probe ...")
		os.Exit(2)
	}
	switch os.Args[1] {
	case "sample":
		runSample(os.Args[2:])
	case "probe":
		runProbe(os.Args[2:])
	default:
		fmt.Fprintln(os.Stderr, "perintah tidak dikenal")
		os.Exit(2)
	}
}

// ---------- sampler ----------

type target struct {
	name, cid string
	pid       int
	proc      bool
	base      string
}

type multi []string

func (m *multi) String() string     { return strings.Join(*m, ",") }
func (m *multi) Set(s string) error { *m = append(*m, s); return nil }

func runSample(args []string) {
	fs := flag.NewFlagSet("sample", flag.ExitOnError)
	out := fs.String("out", "/results/sampler.csv", "file CSV")
	interval := fs.Duration("interval", time.Second, "interval")
	var ts multi
	fs.Var(&ts, "target", "nama:cid:pid[:noproc]")
	_ = fs.Parse(args)

	var targets []target
	for _, s := range ts {
		p := strings.Split(s, ":")
		if len(p) < 3 {
			fmt.Fprintln(os.Stderr, "target tidak valid:", s)
			os.Exit(2)
		}
		pid, _ := strconv.Atoi(p[2])
		t := target{name: p[0], cid: p[1], pid: pid, proc: !(len(p) > 3 && p[3] == "noproc")}
		for _, cand := range []string{"/sys/fs/cgroup/docker/" + t.cid, "/sys/fs/cgroup/system.slice/docker-" + t.cid + ".scope"} {
			if _, err := os.Stat(cand); err == nil {
				t.base = cand
				break
			}
		}
		targets = append(targets, t)
	}
	f, err := os.Create(*out)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	w := bufio.NewWriter(f)
	fmt.Fprintln(w, "ts_ms,target,ok,cpu_usage_us,cpu_user_us,cpu_system_us,nr_periods,nr_throttled,throttled_us,mem_current,mem_peak,mem_anon,mem_file,pids,threads,fds,vol_cs,nonvol_cs,net_rx,net_tx,io_rbytes,io_wbytes")
	_ = w.Flush()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	tick := time.NewTicker(*interval)
	defer tick.Stop()
	for {
		select {
		case <-stop:
			_ = w.Flush()
			_ = f.Close()
			return
		case now := <-tick.C:
			for _, t := range targets {
				fmt.Fprintln(w, sampleOne(now, t))
			}
			_ = w.Flush()
		}
	}
}

func readFile(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func kv(s string) map[string]int64 {
	m := map[string]int64{}
	for _, line := range strings.Split(s, "\n") {
		f := strings.Fields(line)
		if len(f) == 2 {
			v, _ := strconv.ParseInt(f[1], 10, 64)
			m[f[0]] = v
		}
	}
	return m
}

func sampleOne(now time.Time, t target) string {
	if t.base == "" {
		return fmt.Sprintf("%d,%s,0,,,,,,,,,,,,,,,,,,,", now.UnixMilli(), t.name)
	}
	cpu := kv(readFile(t.base + "/cpu.stat"))
	memCur := readFile(t.base + "/memory.current")
	memPeak := readFile(t.base + "/memory.peak")
	ms := kv(readFile(t.base + "/memory.stat"))
	pids := readFile(t.base + "/pids.current")
	var rb, wb int64
	for _, line := range strings.Split(readFile(t.base+"/io.stat"), "\n") {
		for _, tok := range strings.Fields(line) {
			if strings.HasPrefix(tok, "rbytes=") {
				v, _ := strconv.ParseInt(tok[7:], 10, 64)
				rb += v
			} else if strings.HasPrefix(tok, "wbytes=") {
				v, _ := strconv.ParseInt(tok[7:], 10, 64)
				wb += v
			}
		}
	}
	var threads, fds int
	var vol, nonvol, rx, tx int64
	if t.proc && t.pid > 0 {
		tasks, _ := filepath.Glob(fmt.Sprintf("/proc/%d/task/*", t.pid))
		threads = len(tasks)
		for _, task := range tasks {
			st := kv(strings.ReplaceAll(readFile(task+"/status"), ":", " "))
			vol += st["voluntary_ctxt_switches"]
			nonvol += st["nonvoluntary_ctxt_switches"]
		}
		if ents, err := os.ReadDir(fmt.Sprintf("/proc/%d/fd", t.pid)); err == nil {
			fds = len(ents)
		}
		for _, line := range strings.Split(readFile(fmt.Sprintf("/proc/%d/net/dev", t.pid)), "\n") {
			line = strings.TrimSpace(line)
			if strings.HasPrefix(line, "eth0:") {
				f := strings.Fields(strings.TrimPrefix(line, "eth0:"))
				if len(f) >= 9 {
					rx, _ = strconv.ParseInt(f[0], 10, 64)
					tx, _ = strconv.ParseInt(f[8], 10, 64)
				}
			}
		}
	}
	return fmt.Sprintf("%d,%s,1,%d,%d,%d,%d,%d,%d,%s,%s,%d,%d,%s,%d,%d,%d,%d,%d,%d,%d,%d",
		now.UnixMilli(), t.name, cpu["usage_usec"], cpu["user_usec"], cpu["system_usec"], cpu["nr_periods"], cpu["nr_throttled"], cpu["throttled_usec"],
		memCur, memPeak, ms["anon"], ms["file"], pids, threads, fds, vol, nonvol, rx, tx, rb, wb)
}

// ---------- probe ----------

func runProbe(args []string) {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "pakai: sampler probe wait|first|burst|get|now")
		os.Exit(2)
	}
	cmd := args[0]
	fs := flag.NewFlagSet("probe", flag.ExitOnError)
	url := fs.String("url", "", "URL penuh (wait/get)")
	base := fs.String("base", "", "base URL (first/burst)")
	interval := fs.Duration("interval", 10*time.Millisecond, "interval polling")
	timeout := fs.Duration("timeout", 60*time.Second, "batas waktu")
	n := fs.Int("n", 100, "jumlah request (burst)")
	_ = fs.Parse(args[1:])

	switch cmd {
	case "now":
		fmt.Println(time.Now().UnixNano())
	case "get":
		resp, err := http.Get(*url)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		os.Stdout.Write(b)
	case "wait":
		c := &http.Client{Timeout: 250 * time.Millisecond, Transport: &http.Transport{DisableKeepAlives: true}}
		deadline := time.Now().Add(*timeout)
		start := time.Now()
		attempts := 0
		for time.Now().Before(deadline) {
			attempts++
			resp, err := c.Get(*url)
			if err == nil {
				_, _ = io.Copy(io.Discard, resp.Body)
				resp.Body.Close()
				if resp.StatusCode == 200 {
					json.NewEncoder(os.Stdout).Encode(map[string]any{"first_ok_ns": time.Now().UnixNano(), "attempts": attempts, "probe_start_ns": start.UnixNano()})
					return
				}
			}
			time.Sleep(*interval)
		}
		fmt.Fprintln(os.Stderr, "timeout menunggu", *url)
		os.Exit(1)
	case "first", "burst":
		c := &http.Client{Timeout: 30 * time.Second}
		type req struct{ name, method, path, body string }
		seq := []req{
			{"S1", "GET", "/bench/json", ""},
			{"S3", "GET", "/users/1", ""},
			{"S4", "GET", "/users/1/orders?limit=20", ""},
			{"S6", "POST", "/orders", `{"user_id":1,"total_cents":1234,"note":"first request"}`},
		}
		do := func(r req) (int, float64) {
			var body io.Reader
			if r.body != "" {
				body = bytes.NewBufferString(r.body)
			}
			rq, _ := http.NewRequest(r.method, *base+r.path, body)
			if r.body != "" {
				rq.Header.Set("Content-Type", "application/json")
			}
			t0 := time.Now()
			resp, err := c.Do(rq)
			if err != nil {
				return 0, -1
			}
			_, _ = io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
			return resp.StatusCode, float64(time.Since(t0).Microseconds())
		}
		if cmd == "first" {
			out := map[string]any{}
			for _, r := range seq {
				st, us := do(r)
				out[r.name+"_us"] = us
				out[r.name+"_status"] = st
			}
			json.NewEncoder(os.Stdout).Encode(out)
			return
		}
		bad := 0
		for i := 0; i < *n; i++ {
			if st, _ := do(seq[i%len(seq)]); st != 200 && st != 201 {
				bad++
			}
		}
		json.NewEncoder(os.Stdout).Encode(map[string]any{"requests": *n, "bad": bad})
	default:
		fmt.Fprintln(os.Stderr, "perintah probe tidak dikenal")
		os.Exit(2)
	}
}
