plugins {
    id("com.android.application")
    kotlin("android")
}
android {
    namespace = "org.memotrace.recorder"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = "org.memotrace.recorder"
        minSdk = 36
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "org.memotrace.recorder.IsolatedTestRunner"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }
    testOptions { unitTests.isIncludeAndroidResources = true }
    lint {
        warningsAsErrors = true
        checkDependencies = true
    }
}
kotlin { jvmToolchain(21) }
dependencies {
    implementation(project(":capture-core"))
    // Intentional API 36 compatibility pins; upgrades require a new tested toolchain matrix.
    //noinspection GradleDependency
    implementation("androidx.core:core-ktx:1.17.0")
    //noinspection GradleDependency
    implementation("androidx.lifecycle:lifecycle-service:2.9.4")
    //noinspection GradleDependency
    implementation("androidx.camera:camera-camera2:1.5.3")
    //noinspection GradleDependency
    implementation("androidx.camera:camera-lifecycle:1.5.3")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.16.1")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test:rules:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.7.0")
}
