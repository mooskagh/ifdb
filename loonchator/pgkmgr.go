package main

import (
	"archive/zip"
	"bytes"
	"errors"
	"io"
	"io/ioutil"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
)

type Version struct {
	Major  int
	Minor  int
	Patch  int
	Suffix string
}

type VersionedPackage struct {
	Name    string
	Version Version
	Path    string
}

type Package struct {
	Name     string
	Versions map[Version]*VersionedPackage
}

type PackageOverlord struct {
	Rootpath string
	Packages map[string]*Package
}

func ParseVersion(vstr string) *Version {
	re := regexp.MustCompile(`^(\d+)(?:\.(\d+)(?:\.(\d+))?)?(?:-(.*))?$`)
	matches := re.FindStringSubmatch(vstr)
	if matches == nil {
		return nil
	}
	res := &Version{}
	if matches[1] != "" {
		x, err := strconv.Atoi(matches[1])
		if err != nil {
			return nil
		}
		res.Major = x
	}
	if matches[2] != "" {
		x, err := strconv.Atoi(matches[2])
		if err != nil {
			return nil
		}
		res.Minor = x
	}
	if matches[3] != "" {
		x, err := strconv.Atoi(matches[3])
		if err != nil {
			return nil
		}
		res.Patch = x
	}
	res.Suffix = matches[4]
	return res
}

func ParseVersionedPackage(name, rootpath string) *VersionedPackage {
	re := regexp.MustCompile(`^(.*)~(.*)$`)
	matches := re.FindStringSubmatch(name)
	if matches == nil {
		return nil
	}
	res := &VersionedPackage{
		Name: matches[1],
		Path: filepath.Join(rootpath, name),
	}
	v := ParseVersion(matches[2])
	if v == nil {
		return nil
	}
	res.Version = *v
	return res
}

func NewPackageOverlord(path string) (*PackageOverlord, error) {
	res := &PackageOverlord{Packages: make(map[string]*Package)}
	res.Rootpath = path

	files, err := ioutil.ReadDir(path)
	if err != nil {
		return nil, err
	}

	for _, file := range files {
		if !file.IsDir() {
			continue
		}
		vp := ParseVersionedPackage(file.Name(), path)
		if vp != nil {
			_, ok := res.Packages[vp.Name]
			if !ok {
				res.Packages[vp.Name] = &Package{}
			}
			res.Packages[vp.Name].Name = vp.Name
			if res.Packages[vp.Name].Versions == nil {
				res.Packages[vp.Name].Versions = make(map[Version]*VersionedPackage)
			}
			res.Packages[vp.Name].Versions[vp.Version] = vp
		}
	}

	return res, nil
}

func (m *PackageOverlord) HasPackage(name string, version string) (bool, error) {
	v := ParseVersion(version)
	if v == nil {
		return false, errors.New("Плохой формат версии: " + version)
	}
	p, ok := m.Packages[name]
	if !ok {
		return false, nil
	}
	_, ok = p.Versions[*v]
	return ok, nil
}

func Unzip(src *bytes.Buffer, dest string) error {
	srcreader := bytes.NewReader(src.Bytes())
	r, err := zip.NewReader(srcreader, srcreader.Size())
	if err != nil {
		return err
	}
	os.MkdirAll(dest, 0755)

	// Closure to address file descriptors issue with all the deferred .Close() methods
	extractAndWriteFile := func(f *zip.File) error {
		rc, err := f.Open()
		if err != nil {
			return err
		}
		defer func() {
			if err := rc.Close(); err != nil {
				panic(err)
			}
		}()

		path := filepath.Join(dest, f.Name)

		if f.FileInfo().IsDir() {
			os.MkdirAll(path, f.Mode())
		} else {
			os.MkdirAll(filepath.Dir(path), f.Mode())
			f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, f.Mode())
			if err != nil {
				return err
			}
			defer func() {
				if err := f.Close(); err != nil {
					panic(err)
				}
			}()

			_, err = io.Copy(f, rc)
			if err != nil {
				return err
			}
		}
		return nil
	}

	for _, f := range r.File {
		err := extractAndWriteFile(f)
		if err != nil {
			return err
		}
	}

	return nil
}

func (m *PackageOverlord) FetchPackage(lv *LogView, name, version, md5hash string) error {
	url := ServerFetchUrlPrefix + md5hash
	resp, err := http.Get(url)
	if err != nil {
		return err
	}
	buf := new(bytes.Buffer)
	buf.ReadFrom(resp.Body)
	resp.Body.Close()
	lv.AppendText("Распаковываю..")

	dir, err := ioutil.TempDir(m.Rootpath, "tmp")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)

	err = Unzip(buf, dir)
	if err != nil {
		return err
	}

	err = os.Rename(dir, m.GetPackagePath(name, version))
	if err != nil {
		return err
	}

	lv.AppendText("Нормально!")
	return nil
}

func (m *PackageOverlord) GetPackagePath(name string, version string) string {
	return filepath.Join(m.Rootpath, name+"~"+version)
}
