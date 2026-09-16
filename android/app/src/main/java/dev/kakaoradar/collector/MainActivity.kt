package dev.kakaoradar.collector

import android.app.Activity
import android.app.AlertDialog
import android.content.ComponentName
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
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
        root.addView(label("0.1.0 · 폰 안에만 저장 · 서버 전송 없음", 13))

        val overview = card(root)
        status = label("상태 확인 중", 18).also { overview.addView(it) }
        room = label("선택한 방 없음", 14).also { overview.addView(it) }
        counts = label("", 14).also { overview.addView(it) }

        val setup = card(root)
        setup.addView(label("1  알림 접근 허용", 18).apply { setTypeface(null, Typeface.BOLD) })
        setup.addView(label("설정에서 ‘카톡 레이더’를 허용하세요. 카카오톡 단체방의 구조화된 알림만 처리합니다.", 14))
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
                .setMessage("메시지·진단·대상 방 설정을 지웁니다. 이미 내보낸 파일은 남습니다.")
                .setNegativeButton("취소", null).setPositiveButton("삭제") { _, _ ->
                    app.config.enabled = false
                    app.io.execute {
                        runCatching {
                            app.db.runInTransaction { app.db.dao().clearMessages(); app.db.dao().clearSnapshots(); app.db.dao().clearDiagnostics() }
                            app.config.clear()
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
                val summary = "저장 ${dao.count()}건 · 마지막 수집 ${time(config.lastCapture)}\n" +
                    "최근 진단: 대상 알림 ${dao.total("selected_callbacks")}회\n" +
                    "재노출 억제 ${dao.total("suppressed_entries")}건 · 불확실한 창 ${dao.total("uncertain_windows")}회\n" +
                    "미지원/요약 카톡 알림 ${dao.total("unsupported_kakao_callbacks")}회\n" +
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
        val labels = candidates.mapIndexed { index, c -> "${index + 1}. ${c.title} · ${if (c.shortcut.isBlank()) "알림 단위" else "대화 ID"}" }.toTypedArray()
        AlertDialog.Builder(this).setTitle("수집할 방 하나 선택").setItems(labels) { _, index ->
            val choice = candidates[index]
            AlertDialog.Builder(this).setTitle(choice.title)
                .setMessage("이 알림에 연결된 방만 수집합니다. 같은 이름의 방이 여러 개면 실제 알림을 확인하세요. 카톡 업데이트·재부팅 후 방 식별자가 바뀌면 재선택이 필요할 수 있습니다.")
                .setNegativeButton("취소", null).setPositiveButton("이 방 선택") { _, _ ->
                    app.config.select(choice); refresh()
                }.show()
        }.show()
    }

    @Deprecated("Uses platform document picker for this minimal collector")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 100 || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        toast("내보내는 중입니다")
        app.io.execute {
            val result = runCatching {
                val stream = contentResolver.openOutputStream(uri, "wt") ?: error("No stream")
                app.export(stream)
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
