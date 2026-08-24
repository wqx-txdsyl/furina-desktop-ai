> ## Documentation Index

> Fetch the complete documentation index at: https://wiki.agnes-ai.com/llms.txt

> Use this file to discover all available pages before exploring further.



\# Agnes Video V2.0



> 面向文生视频、图生视频和关键帧动画的异步视频生成 API。



<Info>

&#x20; Agnes Video V2.0 是面向生产场景的视频生成模型，支持文生视频、图生视频和关键帧动画。视频生成采用异步任务 API：先创建任务，再通过 `video\_id` 或 `task\_id` 获取结果。

</Info>



<CardGroup cols={2}>

&#x20; <Card title="模型名称" icon="cube">

&#x20;   `agnes-video-v2.0`

&#x20; </Card>



&#x20; <Card title="创建任务" icon="video">

&#x20;   `POST /v1/videos`

&#x20; </Card>



&#x20; <Card title="获取结果" icon="link">

&#x20;   `GET /agnesapi?video\_id=<VIDEO\_ID>`

&#x20; </Card>



&#x20; <Card title="当前价格" icon="tag">

&#x20;   视频时长当前为 `$0 / 秒`

&#x20; </Card>

</CardGroup>



\## 概述



开发者可以使用文本提示词或图片 URL 生成高质量视频。该模型适用于故事讲述、营销视频、产品演示、社交媒体内容、应用动态素材和 AI 创意工作流。



\## 核心能力



<CardGroup cols={2}>

&#x20; <Card title="文生视频" icon="clapperboard">

&#x20;   通过文本提示词直接生成视频。

&#x20; </Card>



&#x20; <Card title="图生视频" icon="image">

&#x20;   将静态图片转化为动态视频。

&#x20; </Card>



&#x20; <Card title="关键帧动画" icon="timeline">

&#x20;   在多个关键帧之间生成流畅过渡。

&#x20; </Card>



&#x20; <Card title="场景运动控制" icon="camera">

&#x20;   通过提示词控制主体动作、镜头运动和场景动态。

&#x20; </Card>



&#x20; <Card title="视觉一致性" icon="eye">

&#x20;   在帧间保持主体、风格和场景一致。

&#x20; </Card>



&#x20; <Card title="电影级输出" icon="film">

&#x20;   生成高质量电影级视频内容。

&#x20; </Card>



&#x20; <Card title="异步 API" icon="clock">

&#x20;   创建任务后再轮询或查询生成结果。

&#x20; </Card>

</CardGroup>



\## 适用场景



<CardGroup cols={2}>

&#x20; <Card title="故事讲述" icon="book-open">

&#x20;   短片、角色场景和叙事片段。

&#x20; </Card>



&#x20; <Card title="营销视频" icon="bullhorn">

&#x20;   产品广告、宣传视频和推广内容。

&#x20; </Card>



&#x20; <Card title="社交媒体内容" icon="share-nodes">

&#x20;   Reels、Shorts、TikTok 风格视频。

&#x20; </Card>



&#x20; <Card title="图片动画" icon="wand-magic-sparkles">

&#x20;   为肖像、产品、角色或场景添加动画效果。

&#x20; </Card>



&#x20; <Card title="产品演示" icon="box">

&#x20;   通过文本或图片生成产品展示视频。

&#x20; </Card>



&#x20; <Card title="关键帧过渡" icon="arrows-left-right">

&#x20;   在不同视觉状态之间生成流畅过渡。

&#x20; </Card>

</CardGroup>



\## 前提条件



<Note>

&#x20; 在接入之前，请确认拥有有效的 Agnes AI API Key，网络可访问 Agnes AI API 网关，并已准备好用于视频生成的文本提示词。图生视频或关键帧动画还需要提供可公开访问的图片 URL。

</Note>



\## API Reference



\### 创建视频任务



```text theme={null}

POST https://apihub.agnes-ai.com/v1/videos

```



\### 获取视频结果：推荐方式



```text theme={null}

GET https://apihub.agnes-ai.com/agnesapi?video\_id=<VIDEO\_ID>

```



\### 获取视频结果：兼容旧版方式



```text theme={null}

GET https://apihub.agnes-ai.com/v1/videos/<TASK\_ID>

```



\### 请求头



```bash theme={null}

\-H "Authorization: Bearer YOUR\_API\_KEY"

\-H "Content-Type: application/json"

```



\## 创建任务参数



| 参数                    | 类型      | 必填 | 说明                               |

| --------------------- | ------- | -- | -------------------------------- |

| `model`               | string  | 是  | 模型名称，使用 `agnes-video-v2.0`。      |

| `prompt`              | string  | 是  | 视频内容的文本描述。                       |

| `image`               | string  | 否  | 图生视频使用的图片 URL。                   |

| `mode`                | string  | 否  | 生成模式，例如 `ti2vid` 或 `keyframes`。  |

| `height`              | integer | 否  | 视频高度，默认值为 `768`。                 |

| `width`               | integer | 否  | 视频宽度，默认值为 `1152`。                |

| `num\_frames`          | integer | 否  | 视频帧数，必须 `≤ 441` 且遵循 `8n + 1` 规则。 |

| `frame\_rate`          | number  | 否  | 视频帧率，支持范围为 `1–60`。               |

| `num\_inference\_steps` | integer | 否  | 推理步数。                            |

| `seed`                | integer | 否  | 随机种子，用于生成可复现结果。                  |

| `negative\_prompt`     | string  | 否  | 反向提示词，描述需要避免的内容。                 |

| `extra\_body.image`    | array   | 否  | 关键帧模式下的输入图片 URL 数组。              |

| `extra\_body.mode`     | string  | 否  | 附加模式设置，例如 `keyframes`。           |



\## 参数标准化



<Note>

&#x20; Agnes Video V2.0 会对部分视频生成参数进行标准化处理。当提交的 `width`、`height` 或宽高比与模型支持规格不完全匹配时，系统会自动映射到最接近的标准输出尺寸。

</Note>



模型目前支持三个标准分辨率档位：`480p`、`720p` 和 `1080p`。



| 宽高比    | 推荐场景                                      |

| ------ | ----------------------------------------- |

| `16:9` | 横版视频、产品演示、网站展示、YouTube 风格内容。              |

| `9:16` | 竖版短视频、移动端内容、TikTok / Reels / Shorts 风格内容。 |

| `1:1`  | 方形视频、社交媒体信息流、角色或产品展示。                     |

| `4:3`  | 传统横版格式和通用演示内容。                            |

| `3:4`  | 竖版演示、肖像或产品为主的内容。                          |



<Tip>

&#x20; 展示任务信息、计算视频时长或排查生成结果问题时，请以 API 响应中的 `size`、`seconds` 和 `metadata.size\_mapping` 等字段为准。

</Tip>



\## 创建任务示例



<Tabs>

&#x20; <Tab title="文生视频">

&#x20;   ```bash theme={null}

&#x20;   curl -X POST https://apihub.agnes-ai.com/v1/videos \\

&#x20;     -H "Authorization: Bearer YOUR\_API\_KEY" \\

&#x20;     -H "Content-Type: application/json" \\

&#x20;     -d '{

&#x20;       "model": "agnes-video-v2.0",

&#x20;       "prompt": "A cinematic shot of a cat walking on the beach at sunset, soft ocean waves, warm golden lighting, realistic motion",

&#x20;       "height": 768,

&#x20;       "width": 1152,

&#x20;       "num\_frames": 121,

&#x20;       "frame\_rate": 24

&#x20;     }'

&#x20;   ```

&#x20; </Tab>



&#x20; <Tab title="图生视频">

&#x20;   ```bash theme={null}

&#x20;   curl -X POST https://apihub.agnes-ai.com/v1/videos \\

&#x20;     -H "Authorization: Bearer YOUR\_API\_KEY" \\

&#x20;     -H "Content-Type: application/json" \\

&#x20;     -d '{

&#x20;       "model": "agnes-video-v2.0",

&#x20;       "prompt": "The woman slowly turns around and looks back at the camera, natural facial expression, cinematic camera movement",

&#x20;       "image": "https://example.com/image.png",

&#x20;       "num\_frames": 121,

&#x20;       "frame\_rate": 24

&#x20;     }'

&#x20;   ```

&#x20; </Tab>



&#x20; <Tab title="关键帧动画">

&#x20;   ```bash theme={null}

&#x20;   curl -X POST https://apihub.agnes-ai.com/v1/videos \\

&#x20;     -H "Authorization: Bearer YOUR\_API\_KEY" \\

&#x20;     -H "Content-Type: application/json" \\

&#x20;     -d '{

&#x20;       "model": "agnes-video-v2.0",

&#x20;       "prompt": "Generate a smooth cinematic transition between the keyframes, maintaining visual consistency and natural camera movement",

&#x20;       "extra\_body": {

&#x20;         "image": \[

&#x20;           "https://example.com/keyframe1.png",

&#x20;           "https://example.com/keyframe2.png"

&#x20;         ],

&#x20;         "mode": "keyframes"

&#x20;       },

&#x20;       "num\_frames": 121,

&#x20;       "frame\_rate": 24

&#x20;     }'

&#x20;   ```

&#x20; </Tab>

</Tabs>



\## 创建任务响应



```json theme={null}

{

&#x20; "id": "task\_YOUR\_TASK\_ID",

&#x20; "task\_id": "task\_YOUR\_TASK\_ID",

&#x20; "video\_id": "video\_YOUR\_VIDEO\_ID",

&#x20; "object": "video",

&#x20; "model": "agnes-video-v2.0",

&#x20; "status": "queued",

&#x20; "progress": 0,

&#x20; "created\_at": 1780457477,

&#x20; "seconds": "10.0",

&#x20; "size": "1280x768"

}

```



| 字段           | 类型      | 说明                  |

| ------------ | ------- | ------------------- |

| `id`         | string  | 任务 ID，可与旧版查询接口配合使用。 |

| `task\_id`    | string  | 任务 ID，作用与 `id` 相同。  |

| `video\_id`   | string  | 视频 ID，推荐用于获取视频结果。   |

| `object`     | string  | 对象类型，通常为 `video`。   |

| `model`      | string  | 当前任务使用的模型。          |

| `status`     | string  | 当前任务状态。             |

| `progress`   | integer | 当前任务进度百分比。          |

| `created\_at` | integer | 任务创建时间戳。            |

| `seconds`    | string  | 视频时长，单位为秒。          |

| `size`       | string  | 视频分辨率。              |



\## 获取视频结果



<Tabs>

&#x20; <Tab title="推荐方式：video\_id">

&#x20;   ```bash theme={null}

&#x20;   curl --location --request GET 'https://apihub.agnes-ai.com/agnesapi?video\_id=<VIDEO\_ID>' \\

&#x20;     --header 'Authorization: Bearer YOUR\_API\_KEY'

&#x20;   ```

&#x20; </Tab>



&#x20; <Tab title="指定 model\_name">

&#x20;   ```bash theme={null}

&#x20;   curl --location --request GET 'https://apihub.agnes-ai.com/agnesapi?video\_id=<VIDEO\_ID>\&model\_name=agnes-video-v2.0' \\

&#x20;     --header 'Authorization: Bearer YOUR\_API\_KEY'

&#x20;   ```



&#x20;   适用于使用上游原始视频 ID、非默认模型，或需要显式指定模型名称的场景。

&#x20; </Tab>



&#x20; <Tab title="兼容旧版：task\_id">

&#x20;   ```bash theme={null}

&#x20;   curl --location --request GET 'https://apihub.agnes-ai.com/v1/videos/<TASK\_ID>' \\

&#x20;     --header 'Authorization: Bearer YOUR\_API\_KEY'

&#x20;   ```

&#x20; </Tab>

</Tabs>



\## 获取结果响应



任务完成后，最终生成的视频 URL 位于 `metadata.url`。



```json theme={null}

{

&#x20; "id": "task\_YOUR\_TASK\_ID",

&#x20; "video\_id": "task\_YOUR\_TASK\_ID",

&#x20; "task\_id": "task\_YOUR\_TASK\_ID",

&#x20; "object": "video",

&#x20; "model": "agnes-video-v2.0",

&#x20; "status": "completed",

&#x20; "progress": 100,

&#x20; "created\_at": 1784530473,

&#x20; "completed\_at": 1784530510,

&#x20; "seconds": "1.0",

&#x20; "size": "832x448",

&#x20; "metadata": {

&#x20;   "size\_mapping": {

&#x20;     "adjusted": true,

&#x20;     "height": 448,

&#x20;     "message": "Input size 1024x576 was mapped to nearest preset 480p/16:9 (832x448)",

&#x20;     "ratio": "16:9",

&#x20;     "requested\_height": 576,

&#x20;     "requested\_width": 1024,

&#x20;     "resolution": "480p",

&#x20;     "width": 832

&#x20;   },

&#x20;   "url": "https://platform-outputs.agnes-ai.space/videos/agnes-video-v2.0/task\_YOUR\_TASK\_ID.mp4"

&#x20; }

}

```



| 字段                      | 类型            | 说明                                           |

| ----------------------- | ------------- | -------------------------------------------- |

| `id`                    | string        | 任务 ID。                                       |

| `video\_id`              | string        | API 返回的视频 ID。请将其视为不透明 ID；该值可能与 `task\_id` 相同。 |

| `task\_id`               | string        | 任务 ID，作用与 `id` 相同。                           |

| `model`                 | string        | 当前任务使用的模型。                                   |

| `object`                | string        | 对象类型。                                        |

| `status`                | string        | 任务状态。                                        |

| `progress`              | integer       | 任务进度百分比。                                     |

| `created\_at`            | integer       | 任务创建时间戳。                                     |

| `completed\_at`          | integer       | 任务完成时间戳。                                     |

| `seconds`               | string        | 视频时长，单位为秒。                                   |

| `size`                  | string        | 标准化后的实际输出视频分辨率。                              |

| `metadata`              | object        | 结果附加元数据。                                     |

| `metadata.url`          | string        | 最终生成的视频 URL，仅在 `status` 为 `completed` 时可用。   |

| `metadata.size\_mapping` | object        | 尺寸标准化信息，包括请求尺寸、实际输出尺寸、宽高比和分辨率档位。             |

| `error`                 | object / null | 任务失败时返回的错误信息。成功响应中该字段可能不存在。                  |



\## 任务状态



| 状态            | 说明         |

| ------------- | ---------- |

| `queued`      | 任务正在队列中等待。 |

| `in\_progress` | 视频正在生成。    |

| `completed`   | 视频生成成功。    |

| `failed`      | 视频生成失败。    |



\## 视频时长控制



视频时长由 `num\_frames` 和 `frame\_rate` 控制。



```text theme={null}

seconds = num\_frames / frame\_rate

```



<Warning>

&#x20; `num\_frames` 必须小于或等于 `441`，并且必须遵循 `8n + 1` 规则。

</Warning>



| 目标时长   | 推荐参数                                |

| ------ | ----------------------------------- |

| 约 3 秒  | `num\_frames: 81`, `frame\_rate: 24`  |

| 约 5 秒  | `num\_frames: 121`, `frame\_rate: 24` |

| 约 10 秒 | `num\_frames: 241`, `frame\_rate: 24` |

| 约 18 秒 | `num\_frames: 441`, `frame\_rate: 24` |



\## 推荐参数



| 场景       | 推荐设置                                                              |

| -------- | ----------------------------------------------------------------- |

| 标准视频生成   | `width: 1152`, `height: 768`, `num\_frames: 121`, `frame\_rate: 24` |

| 社交短视频    | `num\_frames: 81` 或 `121`, `frame\_rate: 24`                        |

| 较长视频     | 增大 `num\_frames` 或降低 `frame\_rate`。                                 |

| 更流畅的运动   | 使用 `frame\_rate: 24` 或 `30`。                                       |

| 可复现结果    | 设置固定 `seed`。                                                      |

| 关键帧过渡    | 使用 `extra\_body.mode: "keyframes"`。                                |

| 避免不需要的内容 | 使用 `negative\_prompt`。                                             |



\## 提示词最佳实践



<AccordionGroup>

&#x20; <Accordion title="文生视频提示词">

&#x20;   推荐结构：



&#x20;   ```text theme={null}

&#x20;   \[主体] + \[动作] + \[场景] + \[镜头运动] + \[光线] + \[风格]

&#x20;   ```



&#x20;   示例：



&#x20;   ```text theme={null}

&#x20;   A young astronaut walking across a red desert planet, dust blowing in the wind, slow cinematic tracking shot, dramatic sunset lighting, realistic sci-fi style

&#x20;   ```

&#x20; </Accordion>



&#x20; <Accordion title="图生视频提示词">

&#x20;   描述哪些内容应该运动，以及哪些关键主体元素应该保持稳定。



&#x20;   ```text theme={null}

&#x20;   Animate the character with subtle breathing motion, hair moving gently in the wind, background lights flickering softly, while keeping the face and outfit consistent

&#x20;   ```

&#x20; </Accordion>



&#x20; <Accordion title="关键帧动画提示词">

&#x20;   清晰描述关键帧之间的过渡关系。



&#x20;   ```text theme={null}

&#x20;   Create a smooth transition from the first keyframe to the second keyframe, maintaining character identity, consistent camera angle, and natural motion between scenes

&#x20;   ```

&#x20; </Accordion>

</AccordionGroup>



\## 错误码



| 状态码   | 说明               |

| ----- | ---------------- |

| `400` | 请求无效。请检查请求参数。    |

| `401` | 未授权。请检查 API Key。 |

| `404` | 任务或视频未找到。        |

| `500` | 服务器错误。           |

| `503` | 服务繁忙。请稍后重试。      |



\## 定价



| 类型   | 标准价格         | 当前价格     |

| ---- | ------------ | -------- |

| 视频时长 | `$0.005 / 秒` | `$0 / 秒` |



\## 接入检查清单



<Check>

&#x20; 使用 `agnes-video-v2.0` 作为模型名称。

</Check>



<Check>

&#x20; 视频生成是异步任务，需要先创建任务，再获取结果。

</Check>



<Check>

&#x20; 创建任务响应会同时返回 `task\_id` 和 `video\_id`，新接入建议使用 `video\_id`。

</Check>



<Check>

&#x20; `num\_frames` 必须小于或等于 `441`，并遵循 `8n + 1` 规则。

</Check>



<Check>

&#x20; 图生视频使用 `image`，关键帧动画使用 `extra\_body.image`。

</Check>



