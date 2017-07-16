package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"

	"github.com/lxn/walk"
	. "github.com/lxn/walk/declarative"
)

type packageRequest struct {
	Token   string `json:"token,omitempty"`
	Package string `json:"package,omitempty"`
	User    string `json:"user,omitempty"`
}

type packageResponse struct {
	Error string `json:"error"`
}

func fetchPackage(request *packageRequest) (*packageResponse, error) {
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

func runGame(mw *walk.MainWindow, lv *LogView, token string) {
	lv.AppendText("Проверка на наличие обновлений игры...")

	rgreq := packageRequest{
		Token: token,
	}

	_, err := fetchPackage(&rgreq)
	if err != nil {
		lv.AppendText("Ошибка: " + err.Error())
		return
	}

	// mw.Close()
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
		go runGame(mw, lv, u.Path[1:])
	default:
		return errors.New("Непонятная команда:" + u.Hostname())
	}

	mw.Run()
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
