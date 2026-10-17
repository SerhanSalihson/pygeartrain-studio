import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

// pyGearTrain Studio 3D scene. Every part is a Model whose geometry is built in Python; the
// Python side only moves parts (x, y, angle) each frame through the `bridge` object.
Item {
    id: root

    function setView(name) {
        if (name === "top") { orbit.eulerRotation = Qt.vector3d(-89.9, 0, 0) }
        else if (name === "front") { orbit.eulerRotation = Qt.vector3d(-8, 0, 0) }
        else { orbit.eulerRotation = Qt.vector3d(-32, -28, 0) }
        cam.z = 420
    }

    Rectangle { anchors.fill: parent; color: bridge.background }

    View3D {
        id: view
        anchors.fill: parent
        camera: cam
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: bridge.background
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.VeryHigh
            aoEnabled: bridge.ambientOcclusion
            aoStrength: 45
            aoDistance: 8
            aoSoftness: 40
            aoSampleRate: 3
        }

        Node {
            id: orbit
            eulerRotation: Qt.vector3d(-32, -28, 0)
            PerspectiveCamera { id: cam; z: 420; fieldOfView: 34; clipNear: 2; clipFar: 20000 }
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-55, -30, 0)
            brightness: 1.15
            castsShadow: bridge.shadows
            shadowMapQuality: Light.ShadowMapQualityVeryHigh
            shadowFactor: 45
            shadowMapFar: 2500
            pcfFactor: 4
        }
        DirectionalLight { eulerRotation: Qt.vector3d(20, 150, 0); brightness: 0.45; castsShadow: false }
        DirectionalLight { eulerRotation: Qt.vector3d(-80, 0, 0); brightness: 0.25; castsShadow: false }

        Node {
            id: world
            eulerRotation.x: -90          // gear plane horizontal, plates stack upwards

            Repeater3D {
                model: bridge.parts
                delegate: Model {
                    required property var modelData
                    geometry: modelData.geometry
                    visible: modelData.shown
                    position: Qt.vector3d(modelData.px, modelData.py, modelData.pz)
                    eulerRotation.z: modelData.angle
                    scale: Qt.vector3d(1, 1, modelData.sz)
                    castsShadows: modelData.opacity > 0.99
                    receivesShadows: true
                    materials: PrincipledMaterial {
                        baseColor: modelData.color
                        metalness: bridge.metalness
                        roughness: 0.36
                        specularAmount: 0.6
                        opacity: modelData.opacity
                        alphaMode: modelData.opacity < 0.99 ? PrincipledMaterial.Blend : PrincipledMaterial.Opaque
                        depthDrawMode: modelData.opacity < 0.99 ? Material.NeverDepthDraw : Material.OpaqueOnlyDepthDraw
                        cullMode: Material.NoCulling
                    }
                }
            }

            Model {
                visible: bridge.floor
                source: "#Rectangle"
                z: bridge.floorZ
                scale: Qt.vector3d(bridge.floorSize, bridge.floorSize, 1)
                receivesShadows: true
                castsShadows: false
                materials: PrincipledMaterial { baseColor: bridge.floorColor; roughness: 0.95; metalness: 0 }
            }
        }

        OrbitCameraController {
            anchors.fill: parent
            origin: orbit
            camera: cam
        }
    }
}
