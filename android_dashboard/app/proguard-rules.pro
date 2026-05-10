# Proguard rules for GAI MEDashboard
# ProGuard rules for GAI MEDashboard v3 (Compose native)

# OkHttp + Okio
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }

# Data models
-keep class com.lance.gaimedashboard.data.** { *; }

# ViewModel
-keep class com.lance.gaimedashboard.viewmodel.** { *; }

# Kotlin coroutines
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}
-dontwarn kotlinx.coroutines.**

# Compose
-dontwarn androidx.compose.**
