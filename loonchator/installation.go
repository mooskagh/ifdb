package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/lxn/walk"
	"github.com/lxn/win"
	"golang.org/x/sys/windows/registry"
)

func copy(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	cerr := out.Close()
	if err != nil {
		return err
	}
	return cerr
}

func InstallationFlow() error {
	res := walk.MsgBox(nil, "Лунчатор v"+OwnVersion, "Хотите установить лунчатор?",
		walk.MsgBoxYesNo|walk.MsgBoxIconQuestion)

	if res != win.IDYES {
		return nil
	}

	dirDial := &walk.FileDialog{
		Title:          "Куда устанавливаем?",
		InitialDirPath: "::{20d04fe0-3aea-1069-a2d8-08002b30309d}",
	}
	accepted, err := dirDial.ShowBrowseFolder(nil)
	if err != nil {
		return err
	}
	if !accepted {
		return nil
	}

	package_path := filepath.Join(dirDial.FilePath, OwnPackageName+"~"+OwnVersion)
	_ = os.Mkdir(package_path, 0700)

	src, err := filepath.Abs(os.Args[0])
	if err != nil {
		return err
	}
	dst := filepath.Join(package_path, OwnFileName)
	err = copy(src, dst)
	if err != nil {
		return err
	}

	key, _, err := registry.CreateKey(registry.CURRENT_USER, "Software\\Classes\\"+OwnUrlSchema, registry.READ|registry.WRITE)
	if err != nil {
		return err
	}
	defer key.Close()
	if err = key.SetStringValue("", "Ersatzplut:Лунчатор!"); err != nil {
		return err
	}
	if err = key.SetStringValue("URL Protocol", ""); err != nil {
		return err
	}

	key, _, err = registry.CreateKey(key, "shell\\open\\command", registry.READ|registry.WRITE)
	if err != nil {
		return err
	}
	defer key.Close()

	if err = key.SetStringValue("", fmt.Sprintf("\"%s\" \"%%1\"", dst)); err != nil {
		return err
	}

	walk.MsgBox(nil, "Установилось",
		"Вроде бы установилось. Теперь должны работать лунчаторовские кнопки на сайте db.mooskagh.com. Попробуйте.",
		walk.MsgBoxIconInformation)

	return nil
}
