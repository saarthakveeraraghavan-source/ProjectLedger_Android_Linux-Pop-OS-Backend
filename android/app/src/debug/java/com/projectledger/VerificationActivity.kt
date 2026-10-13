package com.projectledger

/** Debug-only test window; keeps verification awake without changing device settings. */
class VerificationActivity : androidx.activity.ComponentActivity() {
    override fun onCreate(state: android.os.Bundle?) {
        super.onCreate(state)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or android.view.WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(android.widget.TextView(this).apply {
            text = "Project Ledger verification\n\nSynthetic data only.\nThis window keeps the screen awake while tests run.\n\nYour phone settings and personal data are unchanged."
            textSize = 20f
            setPadding(40,80,40,40)
            setTextColor(android.graphics.Color.rgb(20,41,56))
            setBackgroundColor(android.graphics.Color.rgb(232,242,243))
        })
    }
}
