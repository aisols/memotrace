import javax.xml.parsers.DocumentBuilderFactory

plugins {
    id("com.android.application") version "8.13.2" apply false
    kotlin("android") version "2.2.21" apply false
    kotlin("jvm") version "2.2.21" apply false
    id("com.diffplug.spotless") version "7.2.1"
}

// Separate finalizer tasks still execute when Gradle skips Test as NO-SOURCE.
gradle.projectsEvaluated {
    subprojects.forEach { component ->
        component.tasks.withType<Test>().forEach { test ->
            test.reports.junitXml.required
                .set(true)
            val resultsGate =
                component.tasks.register("${test.name}Results") {
                    dependsOn(test)
                    doLast {
                        fun gate(
                            condition: Boolean,
                            reason: String,
                        ) {
                            check(condition) { "Test results gate: ${test.path}: $reason" }
                        }
                        gate(
                            !test.testClassesDirs.asFileTree
                                .matching { include("**/*.class") }
                                .isEmpty,
                            "no test class files",
                        )
                        val reports =
                            test.reports.junitXml.outputLocation
                                .get()
                                .asFile
                                .listFiles { f ->
                                    f.name.startsWith("TEST-") &&
                                        f.extension == "xml"
                                }.orEmpty()
                        gate(reports.isNotEmpty(), "missing XML results")
                        val parser =
                            DocumentBuilderFactory
                                .newInstance()
                                .apply {
                                    setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)
                                }.newDocumentBuilder()
                        var total = 0L
                        reports.forEach { file ->
                            val suite = parser.parse(file).documentElement
                            total += suite.getAttribute("tests").toLong()
                            gate(
                                suite.getAttribute("skipped").toLong() == 0L && suite.getElementsByTagName("skipped").length == 0,
                                "skipped tests in ${file.name}",
                            )
                            gate(
                                suite.getAttribute("failures").toLong() == 0L && suite.getAttribute("errors").toLong() == 0L,
                                "failed tests in ${file.name}",
                            )
                        }
                        gate(total > 0, "zero tests")
                    }
                }
            test.finalizedBy(resultsGate)
        }
    }
}

spotless {
    kotlin {
        target("**/src/**/*.kt")
        ktlint("1.7.1")
    }
    kotlinGradle {
        target("*.gradle.kts", "*/build.gradle.kts")
        ktlint("1.7.1")
    }
}

tasks.wrapper {
    gradleVersion = "8.13"
    distributionType = Wrapper.DistributionType.BIN
    distributionSha256Sum = "20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78"
}
