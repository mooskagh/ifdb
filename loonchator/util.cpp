#define UNICODE
#include <windows.h>

#include "util.h"

#ifdef PROD
std::string GetOwnPackageName() { return "loonchator"; }
std::string GetUrlSchema() { return "ersatzplut"; }
std::string GetApiPrefix() { return "http://db.mooskagh.com/api/v0/"; }
#else
std::string GetOwnPackageName() { return "loonchator-debug"; }
std::string GetUrlSchema() { return "ersatzplut-debug"; }
std::string GetApiPrefix() { return "http://localhost:8000/api/v0/"; }
#endif

std::string GetOwnVersion() { return "0.05"; }

std::wstring Conv(const std::string& str) {
  if (str.empty()) return {};
  std::vector<wchar_t> buf(str.size());
  auto sz = MultiByteToWideChar(CP_UTF8, 0, str.data(), str.size(), &buf[0],
                                buf.size());
  return {buf.begin(), buf.begin() + sz};
}

std::string Conv(const std::wstring& str) {
  if (str.empty()) return {};
  std::vector<char> buf(str.size() * 4);
  auto sz = WideCharToMultiByte(CP_UTF8, 0, str.data(), str.size(), &buf[0],
                                buf.size(), 0, nullptr);
  return {buf.begin(), buf.begin() + sz};
}

std::wstring GetExecutableFilename() {
  std::vector<wchar_t> buffer(1024);

  for (;;) {
    DWORD res = GetModuleFileName(0, &buffer[0], buffer.size());
    if (res < buffer.size()) {
      return {buffer.begin(), buffer.begin() + res};
    }
    if (GetLastError() == ERROR_INSUFFICIENT_BUFFER) {
      buffer.resize(buffer.size() * 2);
      continue;
    }
    throw WinException();
  }
}