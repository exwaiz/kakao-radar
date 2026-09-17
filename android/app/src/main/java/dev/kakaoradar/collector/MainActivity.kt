package dev.kakaoradar.collector

import android.app.Activity
import android.app.AlertDialog
import android.content.ComponentName
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.InputType
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.view.View
import android.widget.*
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : Activity() {
    private val app get() = application as RadarApp
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private lateinit var counts: TextView
    private lateinit var room: TextView
    private lateinit var preview: TextView
    private lateinit var toggle: Button
    private var resumed = false
    private var loading = false
    private val refreshLoop = object : Runnable {
        override fun run() { refresh(); if (resumed) handler.postDelayed(this, 3000) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val scroll = ScrollView(this).apply { setBackgroundColor(Color.rgb(243, 246, 245)); isFillViewport = true }
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(22), dp(24), dp(22), dp(28)) }
        scroll.addView(root)
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            view.setPadding(0, insets.systemWindowInsetTop, 0, insets.systemWindowInsetBottom)
            insets
        }
        setContentView(scroll)
        root.addView(label("KAKAO RADAR   /   수집 검증", 12, Color.rgb(8, 127, 114)))
        root.addView(label("놓친 대화의 흐름을\n모으는 첫 단계", 28).apply { setTypeface(null, Typeface.BOLD) })
        root.addView(label("0.3.0 · 알림 수집과 선택한 서버 동기화", 13))

        val overview = card(root)
        status = label("상태 확인 중", 18).also { overview.addView(it) }
        room = label("선택한 방 없음", 14).also { overview.addView(it) }
        counts = label("", 14).also { overview.addView(it) }

        val setup = card(root)
        setup.addView(label("1  알림 접근 허용", 18).apply { setTypeface(null, Typeface.BOLD) })
        setup.addView(label("설정에서 ‘카톡 레이더’를 허용하세요. 그룹 여부가 확인된 카카오톡 알림만 처리합니다.", 14))
        button(setup, "알림 접근 설정 열기") { startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
        button(setup, "알림 연결 다시 요청") {
            NotificationListenerService.requestRebind(ComponentName(this, CollectorService::class.java))
            toast("재연결을 요청했습니다")
        }
        setup.addView(label("2  대상 방 선택", 18).apply { setTypeface(null, Typeface.BOLD) })
        setup.addView(label("대상 방의 카톡 알림을 켜고 새 메시지를 기다리세요. 발견한 방 이름은 선택용으로 표시되며, 원문은 수집을 시작한 방만 저장합니다.", 14))
        button(setup, "발견한 방에서 선택") { chooseRoom() }
        toggle = button(setup, "수집 시작") {
            when {
                app.config.enabled -> { app.config.enabled = false; refresh() }
                app.config.binding == null -> toast("대상 방을 먼저 선택하세요")
                !accessGranted() -> toast("알림 접근을 먼저 허용하세요")
                else -> { app.config.enabled = true; toast("이제 도착하는 알림부터 수집합니다"); refresh() }
            }
        }

        val recent = card(root)
        recent.addView(label("최근 저장한 메시지", 18).apply { setTypeface(null, Typeface.BOLD) })
        preview = label("아직 저장된 메시지가 없습니다.", 14).also { recent.addView(it) }

        val sync = card(root)
        sync.addView(label("서버 동기화", 18).apply { setTypeface(null, Typeface.BOLD) })
        sync.addView(label("선택한 방의 저장 메시지를 설정한 서버로 전송합니다. HTTPS 서버와 기기 인증을 설정해야 합니다. 설정 전에는 전송하지 않습니다.", 14))
        button(sync, "서버 연결 설정") { configureSync() }
        button(sync, "지금 동기화") {
            if (app.syncSettings.enabled) { SyncScheduler.kick(this); toast("동기화를 요청했습니다") }
            else toast("서버 연결을 먼저 설정해 주세요")
        }
        button(sync, "동기화 중지") {
            app.syncSettings.enabled = false; SyncScheduler.cancel(this); refresh()
            toast("새 전송을 중지합니다 · 이미 전송 중인 요청은 완료될 수 있습니다")
        }

        val tools = card(root)
        tools.addView(label("검증과 데이터 관리", 18).apply { setTypeface(null, Typeface.BOLD) })
        tools.addView(label("저장 건수는 전체 수집률이 아닙니다. 실제 대화와 내보낸 기록을 비교해 누락을 확인하세요. 원문은 7일이 지난 뒤 앱이 실행되거나 알림을 처리할 때 정리됩니다.", 14))
        button(tools, "원문 포함 JSONL 내보내기") {
            AlertDialog.Builder(this).setTitle("대화 원문을 파일로 저장합니다")
                .setMessage("선택한 방의 대화 원문·방 이름·가명 발신자가 포함됩니다. 저장 위치에 따라 클라우드에 동기화될 수 있습니다. 파일 사본은 앱에서 자동 삭제되지 않습니다.")
                .setNegativeButton("취소", null).setPositiveButton("저장 위치 선택") { _, _ ->
                    startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "application/octet-stream"
                        putExtra(Intent.EXTRA_TITLE, "kakao-radar-${System.currentTimeMillis()}.jsonl")
                    }, 100)
                }.show()
        }
        button(tools, "진단만 내보내기 · 원문 없음") {
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/octet-stream"
                putExtra(Intent.EXTRA_TITLE, "kakao-radar-diagnostics-${System.currentTimeMillis()}.jsonl")
            }, 101)
        }
        button(tools, "HyperOS 검증 안내") {
            AlertDialog.Builder(this).setTitle("Redmi Note 14 5G 검증")
                .setMessage("① 기본 설정에서 수집 여부 확인\n② 화면을 끄고 야간 6~8시간 비교\n③ 필요하면 카톡·수집 앱의 자동 시작과 배터리 설정 비교\n④ 재부팅 후 잠금 해제 전후 비교\n\n설정의 ‘강제 종료’ 후에는 앱을 다시 열어 주세요. 정확한 메뉴 위치는 ROM에 따라 다를 수 있습니다.")
                .setPositiveButton("확인", null).show()
        }
        button(tools, "앱 정보·배터리 설정") {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }
        button(tools, "수집 중지하고 로컬 기록 삭제") {
            AlertDialog.Builder(this).setTitle("로컬 기록을 삭제할까요?")
                .setMessage("메시지·대기열·진단·대상 방·서버 설정을 지웁니다. 서버에 저장한 기록과 내보낸 파일은 남습니다. 서버 삭제는 서버 관리 절차를 따르세요.")
                .setNegativeButton("취소", null).setPositiveButton("삭제") { _, _ ->
                    app.config.enabled = false
                    app.syncSettings.enabled = false
                    SyncScheduler.cancel(this)
                    app.io.execute {
                        runCatching {
                            synchronized(app.syncLock) {
                                app.db.runInTransaction { app.db.dao().clearQueue(); app.db.dao().clearMessages(); app.db.dao().clearSnapshots(); app.db.dao().clearDiagnostics(); app.db.dao().clearStructures() }
                                app.config.clear(); app.syncSettings.clear()
                            }
                        }.onFailure { app.config.error = "삭제 실패 · 다시 시도해 주세요" }
                        runOnUiThread { refresh() }
                    }
                }.show()
        }
        root.addView(label("알림에 보이지 않는 메시지·사진 본문·과거 전체 대화는 수집하지 못할 수 있습니다. AI 요약은 다음 단계에서 연결합니다.", 12))
    }

    override fun onResume() { super.onResume(); resumed = true; handler.post(refreshLoop) }
    override fun onPause() { resumed = false; handler.removeCallbacks(refreshLoop); super.onPause() }

    private fun accessGranted(): Boolean {
        val setting = Settings.Secure.getString(contentResolver, "enabled_notification_listeners").orEmpty()
        return setting.split(':').any { ComponentName.unflattenFromString(it)?.packageName == packageName }
    }

    private fun refresh() {
        if (isFinishing || isDestroyed || loading) return
        loading = true
        val config = app.config
        status.text = when {
            !accessGranted() -> "알림 접근 권한이 필요해요"
            !app.listenerConnected -> "알림 서비스 연결 대기"
            config.enabled -> "● 수집 중"
            else -> "수집 일시 중지"
        }
        room.text = "대상 방: ${config.binding?.title ?: "선택 전"}"
        toggle.text = if (config.enabled) "수집 중지" else "수집 시작"
        app.io.execute {
            try {
                app.pruneIfDue()
                val dao = app.db.dao()
                val reasons = dao.reasons().joinToString("\n") { entry ->
                    val name = entry.code.removePrefix("unsupported_").uppercase(Locale.ROOT)
                    val title = ParseReason.entries.firstOrNull { it.name == name }?.label ?: "기타"
                    "$title ${entry.total}회"
                }.ifEmpty { "없음" }
                val summary = "저장 ${dao.count()}건 · 마지막 수집 ${time(config.lastCapture)}\n" +
                    "전송 대기 ${dao.queueCount("pending")} · 전송 완료 ${dao.queueCount("sent")} · 거절 ${dao.queueCount("rejected")}건\n" +
                    "동기화 ${if (app.syncSettings.enabled) "켜짐" else "꺼짐"} · 마지막 전송 ${time(app.syncSettings.lastSync)}\n" +
                    "미전송 만료 ${dao.total("expired_unsent")} · 한도 초과 ${dao.total("queue_overflow_entries")}건\n" +
                    (if (app.syncSettings.error.isNotBlank()) "${app.syncSettings.error}\n" else "") +
                    "최근 진단: 카톡 도착 ${dao.total("kakao_callbacks")} → 해석 ${dao.total("parsed_callbacks")} → 대상 방 ${dao.total("selected_callbacks")}회\n" +
                    "재연결 시 기존 알림 확인 ${dao.total("discovery_snapshots")} / 해석 ${dao.total("parsed_snapshots")}회\n" +
                    "재노출 억제 ${dao.total("suppressed_entries")}건 · 불확실한 창 ${dao.total("uncertain_windows")}회\n" +
                    "제외 원인(기존 알림 확인 포함):\n$reasons\n" +
                    "처리 오류 ${dao.total("processing_errors")}회 · 이전 버전 미지원 ${dao.total("unsupported_kakao_callbacks")}회\n" +
                    "마지막 연결 ${time(config.lastConnected)}" + if (config.error.isNotBlank()) "\n${config.error}" else ""
                val recent = dao.recent().joinToString("\n\n") {
                    "${time(it.observedAt)} · ${it.sender.take(8)}${if (it.quality != "structured") " · 순서 확인 필요" else ""}\n${it.text.take(350)}"
                }.ifEmpty { "아직 저장된 메시지가 없습니다. 방을 선택하고 수집을 시작해 주세요." }
                runOnUiThread { if (!isDestroyed) { counts.text = summary; preview.text = recent }; loading = false }
            } catch (_: Exception) {
                runOnUiThread { if (!isDestroyed) counts.text = "저장소를 읽지 못했습니다."; loading = false }
            }
        }
    }

    private fun chooseRoom() {
        val candidates = app.config.candidates()
        if (candidates.isEmpty()) {
            AlertDialog.Builder(this).setTitle("아직 발견된 방이 없습니다")
                .setMessage("알림 접근을 허용한 뒤 대상 카톡방의 알림을 켜고 새 메시지를 기다려 주세요. 카톡 화면을 닫은 상태에서도 확인해 보세요. 미지원 알림만 늘어나면 해당 카톡 버전의 형식 확인이 필요합니다.")
                .setPositiveButton("확인", null).show()
            return
        }
        val labels = candidates.mapIndexed { index, c ->
            "${index + 1}. ${c.title} · ${c.identityLabel}" +
                if (app.config.hasTitleCollision(c)) " · 동일 제목 ${app.config.alias(c.shortcut.ifBlank { c.key }).take(6)}" else ""
        }.toTypedArray()
        AlertDialog.Builder(this).setTitle("수집할 방 하나 선택").setItems(labels) { _, index ->
            val choice = candidates[index]
            AlertDialog.Builder(this).setTitle(choice.title)
                .setMessage("이 알림에 연결된 방만 수집합니다. 대화 ID가 있으면 알림 키가 바뀌어도 같은 방으로 구분합니다. 같은 제목의 방은 목록의 구분값과 실제 알림을 확인하세요. 대화 ID가 없고 제목이 충돌하면 저장을 보류합니다.")
                .setNegativeButton("취소", null).setPositiveButton("이 방 선택") { _, _ ->
                    app.config.select(choice); refresh()
                }.show()
        }.show()
    }

    private fun configureSync() {
        if (app.config.binding == null) { toast("대상 방을 먼저 선택하세요"); return }
        val panel = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(20),dp(10),dp(20),dp(10)) }
        panel.addView(label("이 방의 연결 ID: ${app.config.roomId}\n서버의 허용 방에도 같은 ID를 등록하세요.",14))
        val server = EditText(this).apply { hint="HTTPS 서버 주소"; setText(app.syncSettings.server); inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI; panel.addView(this) }
        val device = EditText(this).apply { hint="기기 ID (UUID)"; setText(app.syncSettings.device); panel.addView(this) }
        val token = EditText(this).apply { hint="기기 인증 토큰"; inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD; panel.addView(this) }
        val dialog = AlertDialog.Builder(this).setTitle("서버 연결과 전송 시작").setView(panel)
            .setMessage("선택한 방의 저장 원문을 이 서버로 전송합니다. 서버 주소와 인증 정보를 확인하세요.")
            .setNegativeButton("취소",null).setPositiveButton("연결하고 동기화",null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val result=runCatching { app.syncSettings.configure(server.text.toString().trim(), device.text.toString().trim(), app.config.roomId, token.text.toString()) }
                if (result.isSuccess) { SyncScheduler.schedule(this); dialog.dismiss(); refresh(); toast("동기화를 시작합니다") }
                else toast("HTTPS 주소·UUID 기기 ID·32자 이상 토큰을 확인해 주세요")
            }
        }
        dialog.show()
    }

    @Deprecated("Uses platform document picker for this minimal collector")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode !in listOf(100, 101) || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        toast("내보내는 중입니다")
        app.io.execute {
            val result = runCatching {
                val stream = contentResolver.openOutputStream(uri, "wt") ?: error("No stream")
                app.export(stream, includeMessages = requestCode == 100)
            }
            runOnUiThread { toast(if (result.isSuccess) "내보내기 완료" else "내보내기 실패 · 저장 위치를 확인해 주세요") }
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun label(text: String, size: Int, color: Int = Color.rgb(28, 45, 42)) = TextView(this).apply {
        this.text = text; textSize = size.toFloat(); setTextColor(color)
        setPadding(0, dp(7), 0, dp(7)); setLineSpacing(dp(3).toFloat(), 1f)
    }
    private fun card(parent: LinearLayout) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; setPadding(dp(17), dp(14), dp(17), dp(14))
        background = GradientDrawable().apply { setColor(Color.WHITE); cornerRadius = dp(18).toFloat() }
        parent.addView(this, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(18) })
    }
    private fun button(parent: LinearLayout, title: String, action: () -> Unit) = Button(this).apply {
        text = title; isAllCaps = false; minHeight = dp(52); setOnClickListener { action() }
        parent.addView(this, LinearLayout.LayoutParams(-1, -2))
    }
    private fun time(at: Long) = if (at == 0L) "없음" else SimpleDateFormat("MM-dd HH:mm:ss", Locale.KOREA).format(Date(at))
    private fun toast(message: String) { Toast.makeText(this, message, Toast.LENGTH_LONG).show() }
}
