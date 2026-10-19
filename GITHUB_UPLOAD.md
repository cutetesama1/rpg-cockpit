当前仓库：https://github.com/cutetesama1/rpg-cockpit

以下首次上传步骤供参考；仓库已有内容时请先克隆或拉取。日常更新使用文末的更新命令。

# Windows 上传到 GitHub

上传目录：`E:\work\RPG-Cockpit-GitHub-Ready`。

该目录包含README、Apache-2.0许可证、第三方说明、新图标与封面。使用整个目录内的源文件建立仓库；不要只把源码ZIP当成一个文件上传。

## 1. 创建空仓库

登录 https://github.com/new ，填写：

- Repository name：`rpg-cockpit`
- Description：复制PROJECT_DESCRIPTION.md中的中文简介。
- Visibility：`Public`。
- 不勾选生成README，不另外选择.gitignore和License，因为本地已提供。

点击Create repository，记下自己的HTTPS仓库地址。

官方说明：https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository

## 2. 初始化并提交源码

电脑已安装Git。打开PowerShell，把以下名称、邮箱和YOUR_GITHUB_USERNAME替换为自己的信息，再执行：

```powershell
Set-Location 'E:\work\RPG-Cockpit-GitHub-Ready'
git init -b main
git config user.name "cutetesama1"
git config user.email "你在GitHub设置的提交邮箱"
git add .
git status --short
git commit -m "Initial open-source release"
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/rpg-cockpit.git
git push -u origin main
```

`user.name`和`user.email`写入此仓库的本地配置，不修改其他仓库。
`git status --short`显示待提交文件；本上传包没有包含原项目Git历史、模型密钥、个人存档和第三方完整立绘。

官方流程：https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github

## 3. 完成登录

本机Git已配置`manager`凭据助手。首次HTTPS推送如弹出登录窗口，选择浏览器登录，完成GitHub授权和可能的双重验证。不需要把登录令牌写到源码或远程URL中。

若登录窗口未正常出现，按Git错误信息处理，认证方式参考：
https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git

## 4. 检查主页

刷新仓库，根目录应直接出现README.md、LICENSE、core、ui、android等文件，而不是多套一层文件夹。README会自动显示图标、介绍与封面。

在仓库About区域补充Topics，可直接使用PROJECT_DESCRIPTION.md中的标签。

## 5. 后续更新

将需要公开的改动同步到这个专用目录，再执行：

```powershell
git add .
git commit -m "Update project"
git push
```

不要把开发目录中的密钥、存档或第三方素材整批复制进来。此上传包中的.gitignore已排除常见本地配置与构建产物。

## 视频与安装包

源码仓库优先保留源文件和小型图片。需要发布视频或可分发的安装包时，可在仓库Releases里创建版本并附加文件，保持素材说明；现成开发APK的素材范围与本源码导出包不同。

Releases官方步骤：https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository

本任务仅准备文案和上传包，没有执行git init、commit或push，也没有创建公开仓库。
