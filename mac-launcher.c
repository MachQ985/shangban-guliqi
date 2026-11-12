#include <mach-o/dyld.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <stdio.h>
int main(void) {
 char path[PATH_MAX]; uint32_t n=sizeof(path);
 if (_NSGetExecutablePath(path,&n)!=0) return 1;
 char resolved[PATH_MAX]; if(!realpath(path,resolved)) return 1;
 for(int i=0;i<4;i++){char *p=strrchr(resolved,'/');if(!p)return 1;*p=0;}
 if(chdir(resolved))return 1;
 /* 按顺序找 python3：python.org 安装包（Current = 最新装的版本）→ Apple 芯片 Homebrew → Intel Homebrew → 系统自带 */
 setenv("PATH","/Library/Frameworks/Python.framework/Versions/Current/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",1);
 freopen("/dev/null","r",stdin);
 freopen("/dev/null","a",stdout);
 freopen("运行日志.log","a",stderr);
 execl("/bin/bash","bash","Mac双击打开.command",(char*)0);
 return 1;
}
