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
        versionCode = 2
        versionName = "0.2.0"
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

class ConnectedApkSafety(
    private val retention: Provider<String>,
    private val incompatibleUninstall: Provider<String>,
) : Action<Task>,
    Describable {
    override fun getDisplayName() = "MemoTrace connected APK safety"

    override fun execute(task: Task) {
        check(retention.orNull == "true" && incompatibleUninstall.orNull == "false") {
            "Connected test safety gate: require android.injected.androidTest.leaveApksInstalledAfterRun=true " +
                "and android.experimental.testOptions.uninstallIncompatibleApks=false; " +
                "effective values: retention=${retention.orNull}, incompatibleUninstall=${incompatibleUninstall.orNull}. " +
                "Refusing before DeviceProvider/install. Never uninstall or clear data as a fallback."
        }
        task.logger.lifecycle("Connected test safety passed: ${task.path}; retain APKs, no incompatible uninstall")
    }
}

val connectedApkSafety =
    ConnectedApkSafety(
        providers.gradleProperty("android.injected.androidTest.leaveApksInstalledAfterRun"),
        providers.gradleProperty("android.experimental.testOptions.uninstallIncompatibleApks"),
    )
val verifyConnectedTestSafety =
    tasks.register("verifyConnectedTestSafety") {
        group = "verification"
        description = "Check effective connected-test APK retention options without accessing a device."
        doLast(connectedApkSafety)
    }

// AGP 8.13.2 names: connectedDebugAndroidTest, connectedReleaseAndroidTest when enabled, and aggregate.
// Its DeviceProvider creation/install is inside the task action, after this doFirst guard.
val connectedTests = tasks.matching { it.name.startsWith("connected") && it.name.endsWith("AndroidTest") }
connectedTests.configureEach {
    dependsOn(verifyConnectedTestSafety)
    doFirst(connectedApkSafety)
}

val verifyConnectedTestSafetyWiring =
    tasks.register("verifyConnectedTestSafetyWiring") {
        group = "verification"
        description = "Verify and execute only the connected-task safety guards, never AGP's device actions."
        notCompatibleWithConfigurationCache("Inspects the pinned connected task action ordering")
        doLast {
            val targets = connectedTests.toList()
            check(targets.any { it.name == "connectedDebugAndroidTest" || it.name == "connectedReleaseAndroidTest" }) {
                "Connected test safety wiring: expected pinned AGP variant task is missing"
            }
            for (target in targets) {
                check(verifyConnectedTestSafety.get() in target.taskDependencies.getDependencies(target)) {
                    "Connected test safety wiring: missing prerequisite for ${target.path}"
                }
                val first = target.actions.firstOrNull()
                check((first as? Describable)?.displayName == connectedApkSafety.displayName) {
                    "Connected test safety wiring: guard is not first for ${target.path}"
                }
                // Deliberately never execute any subsequent action or the connected task itself.
                checkNotNull(first).execute(target)
                if (target.name != "connectedAndroidTest") {
                    // Pinned AGP bean getters only: verify the options AGP will consume, without creating a runner/provider.
                    val factory = target.javaClass.getMethod("getTestRunnerFactory").invoke(target)
                    val keep = factory.javaClass.getMethod("getKeepInstalledApks").invoke(factory) as Provider<*>
                    val uninstall = factory.javaClass.getMethod("getUninstallIncompatibleApks").invoke(factory) as Provider<*>
                    check(keep.get() == true && uninstall.get() == false) {
                        "Connected test safety wiring: AGP factory options disagree for ${target.path}"
                    }
                }
                logger.lifecycle("Verified guard before DeviceProvider action: ${target.path}")
            }
        }
    }

// The existing README/CI command already runs lintDebug; keep all its checks and add this no-device regression.
tasks.matching { it.name == "lintDebug" }.configureEach { dependsOn(verifyConnectedTestSafetyWiring) }
