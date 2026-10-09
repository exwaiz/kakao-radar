package dev.kakaoradar.collector

import android.app.Activity
import android.os.Bundle

/** ADB-only, invisible entry point for Xiaomi devices that block cold broadcast starts. */
class AdbBootstrapActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        finish()
    }
}
