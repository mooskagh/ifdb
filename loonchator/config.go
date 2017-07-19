package main

import (
	"encoding/json"
	"io/ioutil"
	"math/rand"
	"os"
	"path/filepath"
	"time"
)

var letterRunes = []rune("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")

type Config struct {
	User   string `json:"user,omitempty"`
	Client string `json:"client,omitempty"`
}

func configFilename() string {
	path, _ := filepath.Abs(filepath.Dir(os.Args[0]))
	return filepath.Join(path, "loonchator.json")
}

func init() {
	rand.Seed(time.Now().UnixNano())
}

func LoadConfig() Config {
	config, err := os.Open(configFilename())
	res := Config{
		Client: randStringRunes(16),
	}
	if err != nil {
		return res
	}
	defer config.Close()
	jsonParser := json.NewDecoder(config)
	_ = jsonParser.Decode(&res)
	return res
}

func randStringRunes(n int) string {
	b := make([]rune, n)
	for i := range b {
		b[i] = letterRunes[rand.Intn(len(letterRunes))]
	}
	return string(b)
}

func StoreConfig(c Config) {
	data, _ := json.Marshal(c)
	_ = ioutil.WriteFile(configFilename(), data, 0644)
}
