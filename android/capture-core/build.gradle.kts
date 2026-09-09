plugins {
    kotlin("jvm")
    jacoco
}
kotlin { jvmToolchain(21) }
dependencies { testImplementation("junit:junit:4.13.2") }
jacoco { toolVersion = "0.8.13" }
val verifyCoverageInputs by tasks.registering {
    dependsOn(tasks.test)
    doLast {
        check(
            layout.buildDirectory
                .file("jacoco/test.exec")
                .get()
                .asFile
                .let { it.isFile && it.length() > 0 },
        ) {
            "Coverage inputs gate: missing execution data"
        }
        check(
            !sourceSets.main
                .get()
                .output.classesDirs.asFileTree
                .matching { include("**/*.class") }
                .isEmpty,
        ) {
            "Coverage inputs gate: missing production classes"
        }
    }
}
tasks.jacocoTestReport {
    dependsOn(verifyCoverageInputs)
    reports {
        xml.required = true
        csv.required = true
        html.required = true
    }
}
tasks.jacocoTestCoverageVerification {
    dependsOn(tasks.jacocoTestReport)
    violationRules {
        rule {
            limit {
                counter = "LINE"
                minimum = "0.90".toBigDecimal()
            }
            limit {
                counter = "BRANCH"
                minimum = "0.80".toBigDecimal()
            }
        }
    }
}
tasks.check { dependsOn(tasks.jacocoTestCoverageVerification) }
