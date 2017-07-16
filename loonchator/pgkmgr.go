package main

import (
	"errors"
	"io/ioutil"
	"path/filepath"
	"regexp"
	"strconv"
)

type Version struct {
	String string
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
	Versions map[Version]VersionedPackage
}

type PackageOverlord struct {
	Packages map[string]Package
}

func ParseVersion(vstr string) *Version {
	re := regexp.MustCompile(`^(\d+)(?:\.(\d+)(?:\.(\d+))?)?(?:-(.*))?$`)
	matches := re.FindStringSubmatch(vstr)
	if matches == nil {
		return nil
	}
	res := &Version{}
	res.String = vstr
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
	res := &PackageOverlord{}

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
			p := res.Packages[vp.Name]
			p.Name = vp.Name
			if p.Versions == nil {
				p.Versions = make(map[Version]VersionedPackage)
			}
			p.Versions[vp.Version] = *vp
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
