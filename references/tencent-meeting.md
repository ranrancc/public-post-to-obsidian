# Tencent Meeting Replay

## 适用链接

- `https://meeting.tencent.com/crm/...`
- `https://meeting.tencent.com/cw/...`

## 统一入口

腾讯会议回放由：

- `scripts/tencent_meeting_executor.py`

处理。它会再调用旁边的 `tencent-meeting-replay` skill 脚本。

默认行为：

- 先抓逐字稿
- 保存为 Markdown
- 只有在用户明确要求视频时才下载视频

统一入口下载视频示例：

```bash
python3 /Users/zhangyiran/.openclaw/workspace/skills/public-post-to-obsidian/scripts/run_public_capture.py \
  --tencent-meeting-download-video \
  'https://meeting.tencent.com/crm/NA1pgaAR20'
```

## 默认落点

- 根目录是 `~/Library/CloudStorage/OneDrive-个人/讲座录制/`
- 单场回放默认建成 `YYYYMMDD 标题/`
- 若标题能识别为系列内容，比如“第 X 期”，会优先复用已有系列目录
- 找不到已有系列目录时，才新建 `YYYYMMDD 系列名/`

## 实现要点

- 通过本机 Chrome CDP 读取腾讯会议回放页
- 逐字稿面板是可滚动列表，需要滚动提取并去重
- 视频地址通常从页面里的可播放 `<video>` 源读取

## 注意事项

- 若页面没有暴露“逐字稿”面板，就不能硬编 transcript
- 若页面没有可播放视频源，就只能返回 transcript 或明确报缺失
- 视频 URL 常带临时签名；若要下载，最好紧接着抓取后执行
- 若 Chrome 没启动，可先运行 `open -a 'Google Chrome'`
- 若 CDP 仍不可用，打开 `chrome://inspect/#remote-debugging` 确认 remote debugging 开关已启用
