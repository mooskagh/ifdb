#pragma comment(lib, "ole32")
#pragma comment(lib, "shell32")
#pragma comment(lib, "user32")
#pragma comment(lib, "WinInet")

#define UNICODE
#include <WinInet.h>
#include <windows.h>

#include <algorithm>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "installation.h"
#include "packages.h"
#include "util.h"

bool ParseCommandLine(const char* cmd_line, std::string* cmd,
                      std::string* param) {
  std::string s(cmd_line);
  if (s.size() >= 2 && s[0] == '"' && s[s.size() - 1] == '"') {
    s.erase(s.begin());
    s.resize(s.size() - 1);
  }
  auto scheme_and_rest = Partition(s, std::string("://"));
  if (scheme_and_rest.first != GetUrlSchema()) return false;
  auto command_and_param = Partition(scheme_and_rest.second, '/');
  *cmd = command_and_param.first;
  *param = command_and_param.second;
  return true;
}

std::string FetchUrl(const std::string& host, int port, const std::string& path,
                     const std::map<std::string, std::string>& post_params) {
  HINTERNET internet =
      InternetOpen("Ersatzplut Loonchator", INTERNET_OPEN_TYPE_PRECONFIG,
                   nullptr, nullptr, 0);
  if (internet == 0) WinException();
  Finally f1([&]() { InternetCloseHandle(internet); });

  HINTERNET connection = InternetConnect(internet.host.c_str(), port, nullptr,
                                         nullptr, INTERNET_SERVICE_HTTP, 0, 0);
  if (connection == 0) WinException();
  Finally f2([&]() { InternetCloseHandle(connection); });

  HINTERNET request = HttpOpenRequest(connection, "POST", path.c_str(), nullptr,
                                      nullptr, nullptr, 0);
  if (request == 0) WinException();
  Finally f3([&]() { InternetCloseHandle(request); });

  std::string post;
  for (const auto& x : post_params) {
    if (!post.empty()) post += '&';
    post += x.first;
    post += '=';
    post += x.second;
  }

  if (!HttpSendRequest(request, nullptr, 0, post.c_str(), post.size()))
    WinException();
}

void CmdRunGame(const std::string& token) {}

int CALLBACK WinMain(_In_ HINSTANCE hInstance, _In_ HINSTANCE hPrevInstance,
                     _In_ LPSTR lpCmdLine, _In_ int nCmdShow) {
  try {
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    Finally f([]() { CoUninitialize(); });

    if (!IsInstalled() || lpCmdLine[0] == '\0') {
      InstallationFlow();
      return 0;
    }

    std::string cmd;
    std::string param;
    if (!ParseCommandLine(lpCmdLine, &cmd, &param))
      throw StrException("Непонятные параметры командной строки: " +
                         std::string(lpCmdLine));

    if (cmd == "rungame")
      CmdRunGame(param);
    else
      throw StrException("Не могу разобрать командную строку... (" + param +
                         "?)");

  } catch (const Exception& e) {
    MsgBox(e.message());
  }

  return 0;
}