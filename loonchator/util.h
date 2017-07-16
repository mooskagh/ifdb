#pragma once

#define UNICODE
#include <windows.h>
#include <algorithm>
#include <cstdint>
#include <functional>
#include <sstream>
#include <string>
#include <vector>

std::string GetOwnPackageName();
std::string GetUrlSchema();
std::string GetApiPrefix();
std::string GetOwnVersion();

std::wstring Conv(const std::string& str);
std::string Conv(const std::wstring& str);

template <class T>
std::vector<std::basic_string<T>> StringSplit(const std::basic_string<T>& str,
                                              T c) {
  std::vector<std::basic_string<T>> res;
  auto iter = str.begin();
  while (iter != str.end()) {
    auto new_iter = std::find(iter, str.end(), c);
    res.emplace_back(iter, new_iter);
    iter = new_iter;
    if (iter != str.end()) ++iter;
  }
  if (iter != str.end()) res.emplace_back(iter, str.end());
  return res;
}

template <class T>
std::basic_string<T> StringJoin(const std::vector<std::basic_string<T>>& v,
                                T c) {
  if (v.empty()) return {};
  std::basic_string<T> res = v[0];
  for (size_t i = 1; i < v.size(); ++i) {
    res += c;
    res += v[i];
  }
  return res;
}

inline void MsgBox(const std::wstring& message) {
  MessageBox(0, message.c_str(), nullptr, MB_OK);
}

template <class T>
std::pair<std::basic_string<T>, std::basic_string<T>> Partition(
    const std::basic_string<T>& str, T c) {
  auto iter = std::find(str.begin(), str.end(), c);
  if (iter == str.end()) {
    return {str, std::string()};
  }
  return {{str.begin(), iter}, {iter + 1, str.end()}};
}

template <class T>
std::pair<std::basic_string<T>, std::basic_string<T>> Partition(
    const std::basic_string<T>& str, const std::basic_string<T>& c) {
  auto pos = str.find(c);
  if (pos == std::basic_string<T>::npos) {
    return {str, std::string()};
  }
  return {{str.begin(), str.begin() + pos},
          {str.begin() + pos + c.size(), str.end()}};
}

template <class T>
std::pair<std::basic_string<T>, std::basic_string<T>> PartitionRight(
    const std::basic_string<T>& str, T c) {
  auto iter = std::find(str.rbegin(), str.rend(), c);
  if (iter == str.rend()) {
    return {str, std::string()};
  }
  return {{str.begin(), iter.base() - 1}, {iter.base(), str.end()}};
}

std::wstring GetExecutableFilename();

class Exception {
 public:
  virtual ~Exception() {}
  virtual std::wstring message() const = 0;
};

class StrException : public Exception {
 public:
  explicit StrException(const std::wstring& str) : str_(str) {}
  explicit StrException(const std::string& str) : str_(Conv(str)) {}
  std::wstring message() const override { return str_; }

 private:
  std::wstring str_;
};

class WinException : public Exception {
 public:
  WinException() : code_(GetLastError()) {}
  explicit WinException(uint32_t code) : code_(code) {}
  std::wstring message() const override {
    std::wostringstream ss;
    ss << L"Ошибка Windows " << code_;
    return ss.str();
  }

 private:
  const uint32_t code_;
  std::string message_;
};

inline void CHECK(uint32_t code) {
  if (code != 0) throw WinException(code);
}

class Finally {
 public:
  Finally(const std::function<void()>& f) : f_(f) {}
  ~Finally() { f_(); }

 private:
  std::function<void()> f_;
};