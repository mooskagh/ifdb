package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sync"
	"time"

	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"
)

type packageRequest struct {
	Token        string `json:"token,omitempty"`
	Package      string `json:"package,omitempty"`
	User         string `json:"user,omitempty"`
	Client       string `json:"client,omitempty"`
	StartSession bool   `json:"startsession,omitempty"`
}

type logTimeRequst struct {
	Session  string `json:"session"`
	TimeSecs int    `json:"time_secs"`
	Finish   bool   `json:"finish,omitempty"`
}

type packageInfo struct {
	Package string `json:"package"`
	Version string `json:"version"`
	Md5     string `json:"md5"`
}

type packageExecute struct {
	Executable string   `json:"executable"`
	Parameters []string `json:"arguments"`
}

type packageRuntime struct {
	Chdir   string         `json:"chdir"`
	Execute packageExecute `json:"execute"`
}

type sessionResponse struct {
	User    string `json:"user"`
	Session string `json:"session"`
}

type packageResponse struct {
	Session   sessionResponse   `json:"session"`
	Error     string            `json:"error"`
	Pakages   []packageInfo     `json:"packages"`
	Variables map[string]string `json:"variables"`
	Runtime   packageRuntime    `json:"runtime"`
}

func (m *packageRuntime) SubstituteVars(vars *map[string]string) error {
	var err error
	m.Chdir, err = substitueVars(m.Chdir, vars)
	if err != nil {
		return err
	}
	m.Execute.Executable, err = substitueVars(m.Execute.Executable, vars)
	if err != nil {
		return err
	}
	for i, _ := range m.Execute.Parameters {
		m.Execute.Parameters[i], err = substitueVars(m.Execute.Parameters[i], vars)
		if err != nil {
			return err
		}
	}
	return nil

}

var wg sync.WaitGroup

func logTime(session string, seconds int, is_finish bool) {
	request := logTimeRequst{
		Session:  session,
		TimeSecs: seconds,
		Finish:   is_finish,
	}
	b := new(bytes.Buffer)
	err := json.NewEncoder(b).Encode(&request)
	if err != nil {
		return
	}
	res, err := http.Post(OwnServerPrefix+"logtime",
		"application/json; charset=utf-8", b)
	if err != nil {
		return
	}
	res.Body.Close()
}

func fetchPackageMetadata(request *packageRequest) (*packageResponse, error) {
	b := new(bytes.Buffer)
	err := json.NewEncoder(b).Encode(request)
	if err != nil {
		return nil, err
	}

	res, err := http.Post(OwnServerPrefix+"fetchpackage", "application/json; charset=utf-8", b)
	if err != nil {
		return nil, err
	}

	response := &packageResponse{}
	if err = json.NewDecoder(res.Body).Decode(response); err != nil {
		return nil, err
	}

	if response.Error != "" {
		return nil, errors.New("Сервер вернул ошибку: " + response.Error)
	}
	return response, nil
}

func substitueVars(s string, vars *map[string]string) (string, error) {
	re := regexp.MustCompile(`{{([^}]+)}}`)
	for {
		indices := re.FindStringSubmatchIndex(s)
		if indices == nil {
			return s, nil
		}
		v := s[indices[2]:indices[3]]
		sub, ok := (*vars)[v]
		if !ok {
			return "", errors.New("Непонятная какая-то переменная " + v)
		}
		s = s[:indices[0]] + sub + s[indices[1]:]
	}
}

func runGameForSure(mw *walk.MainWindow, lv *LogView, token string) error {
	lv.AppendText("Проверка на наличие обновлений игры...")

	config := LoadConfig()
	rgreq := packageRequest{
		Token:        token,
		StartSession: true,
		User:         config.User,
		Client:       config.Client,
	}

	rgresp, err := fetchPackageMetadata(&rgreq)
	if err != nil {
		return err
	}

	if rgresp.Session.User != "" {
		config.User = rgresp.Session.User
	}
	StoreConfig(config)

	path, err := filepath.Abs(filepath.Join(filepath.Dir(os.Args[0]), ".."))
	if err != nil {
		return err
	}

	pkgmgr, err := NewPackageOverlord(path)
	if err != nil {
		return err
	}

	variables := rgresp.Variables

	for _, v := range rgresp.Pakages {
		ok, err := pkgmgr.HasPackage(v.Package, v.Version)
		if err != nil {
			return err
		}
		if ok {
			lv.AppendText("Пакет " + v.Package + " v" + v.Version + " уже распоследний.")
		} else {
			lv.AppendText("Тянем пакет " + v.Package + " v" + v.Version + "...")
			err = pkgmgr.FetchPackage(lv, v.Package, v.Version, v.Md5)
			if err != nil {
				return err
			}
		}
		variables[v.Package] = pkgmgr.GetPackagePath(v.Package, v.Version)
	}

	rgresp.Runtime.SubstituteVars(&variables)

	if rgresp.Runtime.Execute.Executable == "" {
		return errors.New("Непонятно что запускать. :-\\. Сервер не сказал.")
	}

	chdir := rgresp.Runtime.Chdir
	if chdir != "" {
		lv.AppendText("Идём в " + chdir)
		err = os.Chdir(chdir)
		if err != nil {
			return err
		}
	}

	lv.AppendText(fmt.Sprintf("Запускаем %v", rgresp.Runtime.Execute))

	cmd := exec.Command(rgresp.Runtime.Execute.Executable,
		rgresp.Runtime.Execute.Parameters...)

	err = cmd.Start()
	if err != nil {
		return err
	}

	mw.Close()

	done := make(chan error)
	go func() { done <- cmd.Wait() }()

	total_time := 0.0
	logTime(rgresp.Session.Session, 0, false)

	previous_time := time.Now()

	update_time := func() {
		new_time := time.Now()
		duration := new_time.Sub(previous_time).Seconds()
		if duration > 200 {
			duration = 200
		}
		total_time += duration
		previous_time = new_time
	}

	for {
		select {
		case _ = <-done:
			update_time()
			logTime(rgresp.Session.Session, int(total_time), true)
			return nil
		case <-time.After(123 * time.Second):
			update_time()
			logTime(rgresp.Session.Session, int(total_time), false)
		}
	}
}

func runGame(mw *walk.MainWindow, lv *LogView, token string) {
	err := runGameForSure(mw, lv, token)
	if err != nil {
		lv.AppendText("Ошибка: " + err.Error())
	}
	wg.Done()
}

func startCmdProcessor() error {
	u, err := url.Parse(os.Args[1])
	if err != nil {
		return err
	}

	if u.Scheme != OwnUrlSchema {
		return errors.New("Непонятный параметр командной строки. " + u.Scheme)
	}

	var mw *walk.MainWindow

	if err := (MainWindow{
		AssignTo: &mw,
		Title:    "Лунчатор!",
		MinSize:  Size{320, 100},
		Size:     Size{320, 160},
		Layout:   VBox{MarginsZero: true},
	}.Create()); err != nil {
		return err
	}

	lv, err := NewLogView(mw)
	if err != nil {
		return err
	}

	switch u.Hostname() {
	case "rungame":
		wg.Add(1)
		go runGame(mw, lv, u.Path[1:])
	default:
		return errors.New("Непонятная команда:" + u.Hostname())
	}

	mw.Run()
	wg.Wait()
	return nil
}

func main() {
	if len(os.Args) == 1 {
		if err := InstallationFlow(); err != nil {
			walk.MsgBox(nil, "Ошибка", err.Error(), 0)
		}
		return
	}

	if err := startCmdProcessor(); err != nil {
		walk.MsgBox(nil, "Ошибка", err.Error(), 0)
	}
}
