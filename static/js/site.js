document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', (event) => {
        const targetId = anchor.getAttribute('href');
        if (!targetId || targetId === '#') {
            return;
        }

        const target = document.querySelector(targetId);
        if (!target) {
            return;
        }

        event.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
});

const doctorDataNode = document.getElementById('doctorAvailabilityData');
let doctors = [];

if (doctorDataNode) {
    try {
        doctors = JSON.parse(doctorDataNode.textContent || '[]');
    } catch (error) {
        doctors = [];
    }
}

const doctorSelect = document.getElementById('doctorSelect');
const availabilityPreview = document.getElementById('doctorAvailabilityPreview');

if (doctorSelect && availabilityPreview) {
    const renderAvailability = () => {
        const doctorId = doctorSelect.value;
        if (!doctorId) {
            availabilityPreview.style.display = 'none';
            availabilityPreview.innerHTML = '';
            return;
        }

        const selectedDoctor = doctors.find((doctor) => doctor.id === doctorId);
        if (!selectedDoctor) {
            availabilityPreview.style.display = 'none';
            availabilityPreview.innerHTML = '';
            return;
        }

        const slots = selectedDoctor.availability_slots || [];
        const slotText = slots.length
            ? slots.map((slot) => `${slot.day_label}: ${slot.time_range}`).join('<br>')
            : 'No slots configured yet. Admin will assign availability soon.';

        availabilityPreview.innerHTML = `<strong>${selectedDoctor.name} availability</strong><br>${slotText}`;
        availabilityPreview.style.display = 'block';
    };

    doctorSelect.addEventListener('change', renderAvailability);
    renderAvailability();
}

const detailsButtons = document.querySelectorAll('.doctor-details-trigger');
const modal = document.getElementById('doctorDetailsModal');
const modalImage = document.getElementById('doctorDetailsImage');
const modalTitle = document.getElementById('doctorDetailsTitle');
const modalMeta = document.getElementById('doctorDetailsMeta');
const modalBio = document.getElementById('doctorDetailsBio');
const modalSpecialties = document.getElementById('doctorDetailsSpecialties');
const modalAvailability = document.getElementById('doctorDetailsAvailability');
const modalDocumentWrap = document.getElementById('doctorDetailsDocumentWrap');
const modalDocumentLink = document.getElementById('doctorDetailsDocumentLink');
const fallbackDoctorPhoto = 'https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&w=900&q=80';

const closeDoctorModal = () => {
    if (!modal) {
        return;
    }
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
};

const openDoctorModal = (doctor) => {
    if (!modal || !doctor) {
        return;
    }

    const slots = doctor.availability_slots || [];
    const slotText = slots.length
        ? slots.map((slot) => `${slot.day_label}: ${slot.time_range}`).join('<br>')
        : 'No availability slots configured yet.';

    if (modalImage) {
        modalImage.setAttribute('src', doctor.photo_url || fallbackDoctorPhoto);
        modalImage.setAttribute('alt', `${doctor.name || 'Doctor'} profile photo`);
    }

    if (modalTitle) {
        modalTitle.textContent = doctor.name || 'Doctor details';
    }
    if (modalMeta) {
        modalMeta.textContent = `${doctor.title || ''} | ${doctor.experience_years || 0}+ years`;
    }
    if (modalBio) {
        modalBio.textContent = doctor.bio || 'Doctor profile information will be updated soon.';
    }
    if (modalSpecialties) {
        modalSpecialties.textContent = `Specialties: ${doctor.specialties || 'General physiotherapy'}`;
    }
    if (modalAvailability) {
        modalAvailability.innerHTML = `<strong>Availability</strong><br>${slotText}`;
    }

    if (modalDocumentWrap && modalDocumentLink) {
        if (doctor.document_url) {
            modalDocumentLink.setAttribute('href', doctor.document_url);
            modalDocumentWrap.style.display = 'block';
        } else {
            modalDocumentWrap.style.display = 'none';
            modalDocumentLink.setAttribute('href', '#');
        }
    }

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
};

if (modal && detailsButtons.length > 0) {
    detailsButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const doctorId = button.getAttribute('data-doctor-id');
            if (!doctorId) {
                return;
            }
            const doctor = doctors.find((item) => item.id === doctorId);
            openDoctorModal(doctor);
        });
    });

    modal.querySelectorAll('[data-close-modal="true"]').forEach((closeNode) => {
        closeNode.addEventListener('click', closeDoctorModal);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && modal.classList.contains('open')) {
            closeDoctorModal();
        }
    });
}

const doctorPhotoInputs = document.querySelectorAll('input.doctor-photo-input[type="file"][name="photo_file"]');
const cropModal = document.getElementById('doctorPhotoCropModal');
const cropCanvas = document.getElementById('doctorCropCanvas');
const cropZoom = document.getElementById('doctorCropZoom');
const cropX = document.getElementById('doctorCropX');
const cropY = document.getElementById('doctorCropY');
const cropApply = document.getElementById('doctorCropApply');

if (doctorPhotoInputs.length > 0 && cropModal && cropCanvas && cropZoom && cropX && cropY && cropApply) {
    const ctx = cropCanvas.getContext('2d');
    const state = {
        image: null,
        activeInput: null,
        objectUrl: '',
        zoom: 1,
        offsetX: 0,
        offsetY: 0,
    };

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

    const getDrawRect = () => {
        if (!state.image) {
            return null;
        }

        const canvasW = cropCanvas.width;
        const canvasH = cropCanvas.height;
        const imageW = state.image.naturalWidth;
        const imageH = state.image.naturalHeight;
        const baseScale = Math.max(canvasW / imageW, canvasH / imageH);
        const scale = baseScale * state.zoom;
        const drawW = imageW * scale;
        const drawH = imageH * scale;

        const minX = Math.min(0, canvasW - drawW);
        const maxX = 0;
        const minY = Math.min(0, canvasH - drawH);
        const maxY = 0;

        const centeredX = (canvasW - drawW) / 2;
        const centeredY = (canvasH - drawH) / 2;

        const x = clamp(centeredX + state.offsetX, minX, maxX);
        const y = clamp(centeredY + state.offsetY, minY, maxY);

        return { x, y, drawW, drawH };
    };

    const renderCropCanvas = () => {
        if (!ctx) {
            return;
        }

        ctx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
        ctx.fillStyle = '#f6f7f8';
        ctx.fillRect(0, 0, cropCanvas.width, cropCanvas.height);

        if (!state.image) {
            return;
        }

        const rect = getDrawRect();
        if (!rect) {
            return;
        }

        ctx.drawImage(state.image, rect.x, rect.y, rect.drawW, rect.drawH);
    };

    const closeCropModal = (clearSelection) => {
        cropModal.classList.remove('open');
        cropModal.setAttribute('aria-hidden', 'true');

        if (state.objectUrl) {
            URL.revokeObjectURL(state.objectUrl);
            state.objectUrl = '';
        }

        if (clearSelection && state.activeInput) {
            state.activeInput.value = '';
        }

        state.image = null;
        state.activeInput = null;
        state.zoom = 1;
        state.offsetX = 0;
        state.offsetY = 0;
        cropZoom.value = '1';
        cropX.value = '0';
        cropY.value = '0';
        renderCropCanvas();
    };

    const openCropModal = (input, file) => {
        const objectUrl = URL.createObjectURL(file);
        const image = new Image();

        image.onload = () => {
            state.image = image;
            state.activeInput = input;
            state.objectUrl = objectUrl;
            state.zoom = 1;
            state.offsetX = 0;
            state.offsetY = 0;
            cropZoom.value = '1';
            cropX.value = '0';
            cropY.value = '0';

            cropModal.classList.add('open');
            cropModal.setAttribute('aria-hidden', 'false');
            renderCropCanvas();
        };

        image.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            input.value = '';
            alert('Unable to open this image file. Please choose another file.');
        };

        image.src = objectUrl;
    };

    doctorPhotoInputs.forEach((input) => {
        input.addEventListener('change', () => {
            const file = input.files && input.files[0];
            if (!file) {
                return;
            }

            if (!file.type.startsWith('image/')) {
                alert('Please choose a valid image file.');
                input.value = '';
                return;
            }

            openCropModal(input, file);
        });
    });

    cropZoom.addEventListener('input', () => {
        state.zoom = Number(cropZoom.value) || 1;
        renderCropCanvas();
    });

    cropX.addEventListener('input', () => {
        state.offsetX = Number(cropX.value) || 0;
        renderCropCanvas();
    });

    cropY.addEventListener('input', () => {
        state.offsetY = Number(cropY.value) || 0;
        renderCropCanvas();
    });

    cropApply.addEventListener('click', () => {
        if (!state.image || !state.activeInput) {
            return;
        }

        cropCanvas.toBlob((blob) => {
            if (!blob || !state.activeInput) {
                return;
            }

            const originalName = state.activeInput.files && state.activeInput.files[0]
                ? state.activeInput.files[0].name
                : 'doctor-photo.jpg';
            const finalName = originalName.replace(/\.[a-zA-Z0-9]+$/, '') + '-cropped.jpg';
            const croppedFile = new File([blob], finalName, { type: 'image/jpeg' });
            const transfer = new DataTransfer();
            transfer.items.add(croppedFile);
            state.activeInput.files = transfer.files;

            closeCropModal(false);
        }, 'image/jpeg', 0.92);
    });

    cropModal.querySelectorAll('[data-close-crop-modal="true"]').forEach((node) => {
        node.addEventListener('click', () => closeCropModal(true));
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && cropModal.classList.contains('open')) {
            closeCropModal(true);
        }
    });
}
