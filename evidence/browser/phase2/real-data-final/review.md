# 真实数据项目只读UI复核

项目 `424bd3d9-7626-4498-bc90-703aab564b01`，v4。修复前实际bundle为 `index-CSndD1CO.js`。本次只读浏览器观察到整个项目仍running，7个单元、9张真实课程卡；没有提交分析或检索。

- 1440／768／390三宽文档宽度等于视口宽度，主标题均两行，未见横向溢出。覆盖缺口、部分匹配、项目练习、原平台跳转入口均可读。
- 第一单元显示1/6有内容依据，`pd.read_csv 参数`、`DataFrame.shape 与 dtypes`等仍为缺项；没有将泛Pandas视频宣称覆盖具体项目技能。
- 九张卡均保留实际来源标题、HTTPS B站链接、`target=_blank`和`noopener noreferrer`，没有点击平台页面或验证播放。
- 运行提示与已有部分结果同时显示；键盘Enter进入审阅再返回结果，八次Tab均有可见焦点，两个job ID未变。0写请求、0控制台警告/错误、0运行时错误。

发现真实问题：已结束为partial且0卡的时间解析／时间差单元，由于收到全项目running标志，错误提示继续等待课程返回。已获授权仅修正ProjectVideos的`LearningCoverage.searching`为单元pending/queued/submitted/running状态；新增混合状态用例验证终态0卡不等待、排队仍等待、有部分依据仍可学习。完整84项回归、45Node和构建均通过，记录于相邻`mixed-unit-state/`目录。

初次tablet课程截图发生一次中段绘制空白，desktop/mobile正常；未据此改CSS。需在服务恢复后等待两帧并记录DOM/样式再次复拍，原图保留。

构建后bundle为`index-hGmLMzcm.js`，SHA为`1ab294a8203868e60bb0f66ba6aa42df3c8bfe696a28ff6c6f21128cc4287501`。新构建的真实复拍尚未完成：第一次浏览器启动前GET preflight超时，随后两个独立GET（项目结果、首页）均10秒超时，见`../mixed-unit-state/get-probe.json`。未启停服务、未修改后端、未触API写。后端恢复后才可声称完成新bundle实际复验。
