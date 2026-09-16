package dev.kakaoradar.collector

import android.app.Notification
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat

data class RoomCandidate(val title: String, val key: String, val shortcut: String) {
    fun matches(other: RoomCandidate) = title == other.title &&
        if (shortcut.isNotBlank()) shortcut == other.shortcut else key == other.key
}
data class ParsedNotification(val room: RoomCandidate, val messages: List<ObservedMessage>)

object NotificationParser {
    const val PACKAGE = "com.kakao.talk"
    fun parse(sbn: StatusBarNotification): ParsedNotification? {
        if (sbn.packageName != PACKAGE) return null
        val notification = sbn.notification
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return null
        val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification) ?: return null
        // Plain EXTRA_TITLE could be a direct message sender: never infer a group room from it.
        val title = style.conversationTitle?.toString()?.takeIf { it.isNotBlank() } ?: return null
        if (!style.isGroupConversation) return null
        val room = RoomCandidate(title, sbn.key, notification.shortcutId.orEmpty())
        val messages = style.messages.mapNotNull { message ->
            val text = message.text?.toString()?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            ObservedMessage(message.person?.name?.toString().orEmpty(), text,
                message.timestamp.takeIf { it > 0 })
        }
        return ParsedNotification(room, messages)
    }
}
