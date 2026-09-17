package dev.kakaoradar.collector

import android.app.Notification
import android.os.Bundle
import android.os.Build
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject

data class RoomCandidate(val title: String, val key: String, val shortcut: String, val tag: String = "") {
    fun matches(other: RoomCandidate): Boolean {
        // Kakao's display title changes across updates of the same shortcut.
        // It is a selection label, not an identity constraint when a chat ID exists.
        if (shortcut.isNotBlank()) return shortcut == other.shortcut
        if (title != other.title) return false
        return key == other.key // Legacy binding only; never promote a key to a permanent chat ID.
    }
    val identityLabel get() = if (shortcut.isNotBlank()) "대화 ID" else "알림 단위 · 재선택 가능"
}
data class ParsedNotification(val room: RoomCandidate, val messages: List<ObservedMessage>, val method: String = "messaging_style")

enum class ParseReason(val label: String) {
    OTHER_PACKAGE("다른 앱"), GROUP_SUMMARY("묶음 요약 알림"), NOT_GROUP("개인 대화 표시"),
    GROUP_UNCONFIRMED("그룹 여부 미확인"), NO_CONVERSATION_TITLE("방 제목 없음"),
    NO_TITLE("제목 없음"), NO_TEXT("텍스트 없음"), MALFORMED_MESSAGES("메시지 배열 형식 오류"),
    UNSAFE_TITLE_FALLBACK("제목 대체 조건 부족"), MALFORMED_EXTRAS("알림 필드 형식 오류"),
    MESSAGE_ARRAY_API_UNAVAILABLE("메시지 배열 복구에 Android 11 이상 필요")
}
sealed class ParseResult {
    data class Success(val notification: ParsedNotification) : ParseResult()
    data class Unsupported(val reason: ParseReason) : ParseResult()
}

object NotificationParser {
    const val PACKAGE = "com.kakao.talk"
    const val VERSION = 2
    fun parse(sbn: StatusBarNotification): ParseResult {
        if (sbn.packageName != PACKAGE) return ParseResult.Unsupported(ParseReason.OTHER_PACKAGE)
        return try { parseKakao(sbn) } catch (_: RuntimeException) {
            ParseResult.Unsupported(ParseReason.MALFORMED_EXTRAS)
        }
    }
    private fun parseKakao(sbn: StatusBarNotification): ParseResult {
        val n = sbn.notification
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return ParseResult.Unsupported(ParseReason.GROUP_SUMMARY)
        val extras = n.extras ?: Bundle.EMPTY
        val style = runCatching { NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n) }.getOrNull()
        val explicitGroup = if (extras.containsKey(Notification.EXTRA_IS_GROUP_CONVERSATION)) extras.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION) else null
        if (explicitGroup == false) return ParseResult.Unsupported(ParseReason.NOT_GROUP)
        if (explicitGroup != true && style?.isGroupConversation != true) return ParseResult.Unsupported(ParseReason.GROUP_UNCONFIRMED)
        val conversationTitle = style?.conversationTitle?.toString()?.takeIf { it.isNotBlank() }
            ?: extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)?.toString()?.takeIf { it.isNotBlank() }
        val standardTitle = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.takeIf { it.isNotBlank() }
        val title = conversationTitle ?: standardTitle
            ?: return ParseResult.Unsupported(if (style != null) ParseReason.NO_CONVERSATION_TITLE else ParseReason.NO_TITLE)
        // Kakao 26.8.0 observed on Redmi: group=true, shortcut present, room name in EXTRA_TITLE.
        if (conversationTitle == null && (explicitGroup != true || n.shortcutId.isNullOrBlank()))
            return ParseResult.Unsupported(ParseReason.UNSAFE_TITLE_FALLBACK)
        val room = RoomCandidate(title, sbn.key, n.shortcutId.orEmpty(), sbn.tag.orEmpty())
        val styleMessages = style?.messages.orEmpty().mapNotNull { message ->
            val text = message.text?.toString()?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            ObservedMessage(message.person?.name?.toString().orEmpty(), text, message.timestamp.takeIf { it > 0 })
        }
        if (styleMessages.isNotEmpty()) return ParseResult.Success(ParsedNotification(room, styleMessages,
            if (conversationTitle == null) "messaging_style_title_fallback" else "messaging_style"))
        @Suppress("DEPRECATION")
        val array = extras.getParcelableArray(Notification.EXTRA_MESSAGES)
        if (!array.isNullOrEmpty()) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R)
                return ParseResult.Unsupported(ParseReason.MESSAGE_ARRAY_API_UNAVAILABLE)
            val rawMessages = Notification.MessagingStyle.Message.getMessagesFromBundleArray(array).mapNotNull { message ->
                val text = message.text?.toString()?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
                ObservedMessage(message.senderPerson?.name?.toString().orEmpty(), text, message.timestamp.takeIf { it > 0 })
            }
            if (rawMessages.isNotEmpty()) return ParseResult.Success(ParsedNotification(room, rawMessages, "extra_messages"))
            return ParseResult.Unsupported(ParseReason.MALFORMED_MESSAGES)
        }
        // Preserve displayed text intact; never guess sender or timestamp from presentation text.
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.takeIf { it.isNotBlank() }
            ?: return ParseResult.Unsupported(ParseReason.NO_TEXT)
        return ParseResult.Success(ParsedNotification(room, listOf(ObservedMessage("", text, null)), "standard_extras"))
    }

    fun structure(sbn: StatusBarNotification, result: ParseResult, hash: (String) -> String): String {
        val n = sbn.notification
        val extras = n.extras ?: Bundle.EMPTY
        val knownKeys = listOf(Notification.EXTRA_TITLE, Notification.EXTRA_TEXT, Notification.EXTRA_SUB_TEXT,
            Notification.EXTRA_SUMMARY_TEXT, Notification.EXTRA_CONVERSATION_TITLE, Notification.EXTRA_MESSAGES,
            Notification.EXTRA_IS_GROUP_CONVERSATION, Notification.EXTRA_TEMPLATE,
            "android.hiddenConversationTitle", "android.messagingStyleUser", Notification.EXTRA_MESSAGING_PERSON)
        val style = runCatching { NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n) }.getOrNull()
        fun hasText(key: String) = runCatching { !extras.getCharSequence(key).isNullOrBlank() }.getOrDefault(false)
        @Suppress("DEPRECATION")
        val messageCount = runCatching { extras.getParcelableArray(Notification.EXTRA_MESSAGES)?.size ?: 0 }.getOrDefault(-1)
        val output = JSONObject().put("known_extra_keys", JSONArray(knownKeys.filter { extras.containsKey(it) }))
            .put("extra_key_count", extras.keySet().size).put("messaging_style", style != null)
            .put("group_summary", n.flags and Notification.FLAG_GROUP_SUMMARY != 0)
            .put("group_flag", if (extras.containsKey(Notification.EXTRA_IS_GROUP_CONVERSATION))
                runCatching { extras.getBoolean(Notification.EXTRA_IS_GROUP_CONVERSATION) }.getOrDefault(false) else JSONObject.NULL)
            .put("has_conversation_title", hasText(Notification.EXTRA_CONVERSATION_TITLE))
            .put("has_title", hasText(Notification.EXTRA_TITLE)).put("has_text", hasText(Notification.EXTRA_TEXT))
            .put("has_sub_text", hasText(Notification.EXTRA_SUB_TEXT)).put("has_summary_text", hasText(Notification.EXTRA_SUMMARY_TEXT))
            .put("message_count", messageCount).put("has_shortcut", !n.shortcutId.isNullOrBlank())
            .put("has_tag", !sbn.tag.isNullOrBlank()).put("key_hash", hash(sbn.key))
            .put("shortcut_hash", n.shortcutId?.takeIf { it.isNotBlank() }?.let(hash) ?: JSONObject.NULL)
            .put("tag_hash", sbn.tag?.takeIf { it.isNotBlank() }?.let(hash) ?: JSONObject.NULL)
            .put("title_hash", extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.let(hash) ?: JSONObject.NULL)
            .put("tag_equals_shortcut", !sbn.tag.isNullOrBlank() && sbn.tag == n.shortcutId)
        when (result) {
            is ParseResult.Success -> output.put("result", "parsed").put("method", result.notification.method)
            is ParseResult.Unsupported -> output.put("result", "unsupported").put("reason", result.reason.name.lowercase())
        }
        return output.toString()
    }
}
