import re
import asyncio
from typing import Dict, Optional
from astrbot.api.all import *
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter
from astrbot.api.provider import ProviderRequest, LLMResponse

# 正则表达式匹配括号内容
BRACKET_PATTERN = re.compile(r'[（(］\[【{［｛].*?[）)］】}］｝]')

@register("ultimate_ai_plugin", "长安某", "AI语音", "2.0.0")
class UltimateAIPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.default_characters: Dict[str, str] = {}  # 群组ID: 人物ID
        self.auto_speech_mode: Dict[str, bool] = {}   # 群组ID: 自动语音状态
        self.character_cache: Dict[str, list] = {}    # 群组ID: 人物缓存
        self.text_sending_mode: Dict[str, bool] = {}  # 群组ID: 文字同发状态

    @filter.on_llm_request()
    async def my_custom_hook_1(self, event: AstrMessageEvent, req: ProviderRequest):
        print(req)  # 打印请求的文本
        req.system_prompt += "自定义 system_prompt"

    @filter.on_llm_response()
    async def on_llm_resp(self, event: AstrMessageEvent, resp: LLMResponse):
        print(resp)

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        result = event.get_result()
        if not result or not result.is_llm_result():
            return

        group_id = self._get_group_id(event)
        if not group_id or not self.auto_speech_mode.get(group_id, False):
            return

        chain = result.chain
        clean_text = self._clean_llm_text(chain)
        if clean_text:
            try:
                await self._send_ai_voice(event, clean_text)
            except Exception:
                pass

            if self.text_sending_mode.get(group_id, False):
                # 文字同发状态，输出未处理的文本
                text = "".join([segment.text for segment in chain if isinstance(segment, Plain)])
                try:
                    await event.send(MessageChain([Plain(text)]))
                except Exception:
                    pass
            result.chain = []  # 清空消息链，避免额外发送文字消息

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent):
        pass

    def _clean_llm_text(self, chain) -> str:
        clean_text = ""
        for segment in chain:
            if isinstance(segment, Plain):
                text = BRACKET_PATTERN.sub('', segment.text).strip()
                if text:
                    clean_text += text + "\n"
        return clean_text.strip()

    @command("ai人物列表")
    async def get_ai_characters(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id:
            try:
                await event.send(MessageChain([Plain("⚠️ 该功能仅支持QQ群聊")]))
            except Exception:
                pass
            return

        try:
            if group_id not in self.character_cache:
                await self._refresh_character_cache(event, group_id)

            categories = self.character_cache.get(group_id, [])
            if not categories:
                try:
                    await event.send(MessageChain([Plain("⚠️ 当前没有可用的AI人物")]))
                except Exception:
                    pass
                return

            message = ["🎤 当前可用AI语音人物："]
            for cat in categories:
                if not isinstance(cat, dict):
                    continue

                category_msg = [
                    f"\n▍{cat.get('type', '未分类')}：",
                    f"共 {len(cat.get('characters', []))} 个人物"
                ]

                characters = []
                for idx, char in enumerate(cat.get("characters", []), 1):
                    char_info = [
                        f"{idx}. {char.get('character_name', '未知人物')}",
                        f"   ID: {char.get('character_id', 'N/A')}"
                    ]
                    characters.append("\n".join(char_info))

                if characters:
                    category_msg.extend(characters)
                    message.extend(category_msg)

            try:
                await event.send(MessageChain([Plain("\n".join(message))]))
            except Exception:
                pass

        except Exception:
            try:
                await event.send(MessageChain([Plain("❌ 获取失败：发生未知错误")]))
            except Exception:
                pass

    @command("切换语音模式")
    async def toggle_speech_mode(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id:
            try:
                await event.send(MessageChain([Plain("⚠️ 该功能仅支持QQ群聊")]))
            except Exception:
                pass
            return

        new_mode = not self.auto_speech_mode.get(group_id, False)
        self.auto_speech_mode[group_id] = new_mode

        status = "✅ 已启用自动语音模式" if new_mode else "⛔ 已关闭自动语音模式"
        try:
            await event.send(MessageChain([Plain(
                f"{status}\n"
                f"当前设置：\n"
                f"- 默认模型：{self._get_character_name(group_id) or '未设置'}"
            )]))
        except Exception:
            pass

    @command("设置默认模型")
    async def set_default_character(self, event: AstrMessageEvent, identifier: str):
        group_id = self._get_group_id(event)
        if not group_id:
            try:
                await event.send(MessageChain([Plain("⚠️ 该功能仅支持QQ群聊")]))
            except Exception:
                pass
            return

        try:
            await self._refresh_character_cache(event, group_id)

            target = None
            for cat in self.character_cache.get(group_id, []):
                for char in cat.get("characters", []):
                    if str(char.get("character_id")) == identifier or \
                       char.get("character_name") == identifier:
                        target = char
                        break
                if target:
                    break

            if not target:
                try:
                    await event.send(MessageChain([Plain(f"❌ 未找到匹配人物：{identifier}")]))
                except Exception:
                    pass
                return

            self.default_characters[group_id] = str(target["character_id"])
            try:
                await event.send(MessageChain([Plain(
                    f"✅ 已设置默认模型：\n"
                    f"名称：{target['character_name']}\n"
                    f"ID：{target['character_id']}"
                )]))
            except Exception:
                pass

        except Exception:
            try:
                await event.send(MessageChain([Plain("❌ 设置失败：发生未知错误")]))
            except Exception:
                pass

    @command("切换文字同发")
    async def toggle_text_sending_mode(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id:
            try:
                await event.send(MessageChain([Plain("⚠️ 该功能仅支持QQ群聊")]))
            except Exception:
                pass
            return

        new_mode = not self.text_sending_mode.get(group_id, False)
        self.text_sending_mode[group_id] = new_mode

        status = "✅ 已启用文字同发模式" if new_mode else "⛔ 已关闭文字同发模式"
        try:
            await event.send(MessageChain([Plain(status)]))
        except Exception:
            pass

    async def _refresh_character_cache(self, event, group_id):
        try:
            response = await event.bot.api.call_action(
                'get_ai_characters',
                group_id=group_id,
                chat_type=1,
                timeout=8
            )

            if isinstance(response, dict) and response.get("status") == "ok":
                self.character_cache[group_id] = response.get("data", [])
            elif isinstance(response, list):
                self.character_cache[group_id] = response
            else:
                raise Exception("无效的API响应格式")

        except asyncio.TimeoutError:
            raise Exception("请求超时，请稍后重试")
        except Exception:
            raise

    async def _send_ai_voice(self, event, text):
        group_id = self._get_group_id(event)
        try:
            character = await self._get_current_character(event, group_id)
            await event.bot.api.call_action(
                'send_group_ai_record',
                group_id=group_id,
                character=character["character_id"],
                text=text[:500],  # 限制长度
                timeout=10
            )
        except Exception:
            pass

    async def _get_current_character(self, event, group_id):
        if default_id := self.default_characters.get(group_id):
            for cat in self.character_cache.get(group_id, []):
                for char in cat.get("characters", []):
                    if str(char.get("character_id")) == default_id:
                        return char

        first_char = next(
            (char for cat in self.character_cache.get(group_id, [])
             for char in cat.get("characters", [])),
            None
        )
        if not first_char:
            raise Exception("没有可用的语音模型")
        return first_char

    def _get_group_id(self, event):
        if event.get_platform_name() == "aiocqhttp":
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            if isinstance(event, AiocqhttpMessageEvent):
                return str(event.message_obj.group_id)
        return None

    def _get_character_name(self, group_id):
        if default_id := self.default_characters.get(group_id):
            for cat in self.character_cache.get(group_id, []):
                for char in cat.get("characters", []):
                    if str(char.get("character_id")) == default_id:
                        return char["character_name"]
        return None
